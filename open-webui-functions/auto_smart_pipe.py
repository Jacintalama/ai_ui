"""
title: Auto (Smart)
author: Ralph Benitez
version: 1.0.0
description: Picks the best model for your question. Everyday tasks go to a free model; hard coding and reasoning escalate to your strong paid model (GPT-5.5). Paid is used only when the task needs it.
"""

# Sibling of Auto (Free): same keyword classifier, but it also judges how HARD
# the task is. Easy -> a free OpenRouter model ($0). Hard coding/reasoning ->
# a strong paid OpenAI model. Two providers because Open WebUI has no Anthropic
# connection, so paid escalation targets OpenAI. Model ids are Valves, so the
# free/paid picks and the difficulty threshold are all editable without a
# redeploy. Free-model ids rotate; re-check the live OpenRouter list if a route
# starts failing.

import json
import os
import re
from typing import Any, AsyncIterator, Callable, Optional, Union

import httpx
from pydantic import BaseModel, Field

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# OpenAI's newer reasoning family takes `max_completion_tokens` and rejects
# `max_tokens` and `temperature`. Verified against the live API 2026-07-23:
#   "Unsupported parameter: 'max_tokens' is not supported with this model.
#    Use 'max_completion_tokens' instead."
# Without this the paid tier (PAID_* default to gpt-5.5) failed every escalated
# request and silently fell back to the gpt-4o candidate. Same split
# fusion_engine.PROVIDER_REGISTRY encodes as the "openai_new" contract.
# Free OpenRouter ids are namespaced ("openai/gpt-oss-20b:free") so they do not
# match, and are correctly left on the plain contract.
_COMPLETION_TOKEN_MODELS = re.compile(r"^(gpt-5|o[1-9])")


def _needs_completion_tokens(model: str) -> bool:
    return bool(_COMPLETION_TOKEN_MODELS.match((model or "").strip()))

DEFAULT_CATEGORY = "general"

RULES = {
    "coder": [
        "code", "coding", "program", "programming", "function", "bug", "debug",
        "error", "exception", "traceback", "stack trace", "compile", "syntax",
        "refactor", "api", "endpoint", "regex", "query", "sql", "database",
        "python", "javascript", "typescript", "java", "golang", "rust", "c++",
        "html", "css", "react", "docker", "kubernetes", "git", "algorithm",
        "script", "class", "variable", "array", "loop",
    ],
    "reasoning": [
        "solve", "calculate", "compute", "equation", "math", "mathematics",
        "algebra", "geometry", "calculus", "integral", "derivative",
        "probability", "proof", "prove", "theorem", "logic", "puzzle", "riddle",
        "reason", "reasoning", "step by step", "how many", "what is the value",
    ],
}

# Signals that a task is hard enough to be worth a paid model.
HARD_SIGNALS = [
    "debug", "optimize", "optimise", "refactor", "architecture", "concurrency",
    "performance", "algorithm", "distributed", "scalable", "scale", "security",
    "race condition", "memory leak", "benchmark", "design", "prove", "derive",
    "theorem", "proof", "complex", "trade-off", "tradeoff", "in detail",
    "step by step", "explain why", "edge case",
]
HARD_REASONING = ["prove", "derive", "theorem", "proof", "step by step", "multi-step"]

# On a rate-limit (429) or error, retry these in order. Free path stays free;
# paid path escalates to another strong OpenAI model.
FREE_FALLBACK = [
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "google/gemma-4-26b-a4b-it:free",
]
PAID_FALLBACK = ["gpt-4o"]


def _last_user_text(messages) -> str:
    for m in reversed(messages or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _score(text: str, keywords) -> int:
    hits = 0
    for kw in keywords:
        if kw.isalpha():
            if re.search(rf"\b{re.escape(kw)}\b", text):
                hits += 1
        elif kw in text:
            hits += 1
    return hits


def classify_category(text: str) -> str:
    scores = {cat: _score(text, kws) for cat, kws in RULES.items()}
    if "```" in text:
        scores["coder"] = scores.get("coder", 0) + 3
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else DEFAULT_CATEGORY


def is_hard(text: str, category: str, length_threshold: int) -> bool:
    """Worth escalating to a paid model?"""
    if "```" in text:               # real code, not a one-liner
        return True
    if len(text) > length_threshold:  # long, detailed prompt
        return True
    if _score(text, HARD_SIGNALS) >= 2:
        return True
    if category == "reasoning" and _score(text, HARD_REASONING) >= 1:
        return True
    return False


def route(text: str, length_threshold: int) -> tuple[str, bool]:
    """Return (category, hard)."""
    low = text.lower()
    if not low.strip():
        return DEFAULT_CATEGORY, False
    category = classify_category(low)
    return category, is_hard(low, category, length_threshold)


class Pipe:
    class Valves(BaseModel):
        OPENROUTER_API_KEY: str = Field(
            default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", ""),
            description="OpenRouter key for the free tier (read from env).",
        )
        OPENAI_API_KEY: str = Field(
            default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""),
            description="OpenAI key for paid escalation (read from env).",
        )
        # Free models for everyday tasks (OpenRouter :free ids, they rotate).
        FREE_GENERAL: str = Field(default="openai/gpt-oss-20b:free")
        FREE_CODER: str = Field(default="cohere/north-mini-code:free")
        FREE_REASONING: str = Field(default="nvidia/nemotron-3-super-120b-a12b:free")
        # Paid models for hard tasks (OpenAI ids).
        PAID_GENERAL: str = Field(default="gpt-5.5")
        PAID_CODER: str = Field(default="gpt-5.5")
        PAID_REASONING: str = Field(default="gpt-5.5")
        HARD_LENGTH_THRESHOLD: int = Field(
            default=400, description="Prompts longer than this escalate to paid.")
        SHOW_ROUTE: bool = Field(default=True)
        TIMEOUT_SECONDS: int = Field(default=180)

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "auto-smart", "name": "Auto (Smart)"}]

    def _target(self, category: str, hard: bool) -> tuple[str, str, str]:
        """Return (provider, model, tier)."""
        v = self.valves
        if hard:
            model = {"coder": v.PAID_CODER, "reasoning": v.PAID_REASONING}.get(
                category, v.PAID_GENERAL)
            return "openai", model, "paid"
        model = {"coder": v.FREE_CODER, "reasoning": v.FREE_REASONING}.get(
            category, v.FREE_GENERAL)
        return "openrouter", model, "free"

    def _payload(self, body: dict, model: str) -> dict:
        out = {"model": model, "messages": body.get("messages") or []}
        reasoning = _needs_completion_tokens(model)
        for k in ("stream", "temperature", "top_p", "max_tokens"):
            if body.get(k) is None:
                continue
            if reasoning and k == "max_tokens":
                out["max_completion_tokens"] = body[k]
            elif reasoning and k == "temperature":
                continue  # rejected outright by this family
            else:
                out[k] = body[k]
        return out

    async def _emit(self, emitter, desc, done=False):
        if emitter:
            await emitter({"type": "status", "data": {"description": desc, "done": done}})

    def _candidates(self, provider: str, model: str) -> list:
        pool = FREE_FALLBACK if provider == "openrouter" else PAID_FALLBACK
        out = [model]
        for m in pool:
            if m not in out:
                out.append(m)
        return out

    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> Union[str, AsyncIterator[str]]:
        text = _last_user_text(body.get("messages") or [])
        category, hard = route(text, self.valves.HARD_LENGTH_THRESHOLD)
        provider, model, tier = self._target(category, hard)

        if not body.get("messages"):
            return "No message to answer."
        if provider == "openrouter":
            key = self.valves.OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY", "")
            url, refhdr = OPENROUTER_URL, True
        else:
            key = self.valves.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
            url, refhdr = OPENAI_URL, False
        if not key:
            return (f"Auto (Smart) can't reach the {provider} provider: its API key "
                    f"is missing from the environment.")

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if refhdr:
            headers["HTTP-Referer"] = "https://ai-ui.coolestdomain.win"
            headers["X-Title"] = "AIUI Auto Smart"
        candidates = self._candidates(provider, model)

        if body.get("stream"):
            return self._stream(body, headers, url, category, tier, candidates, __event_emitter__)
        return await self._complete(body, headers, url, category, tier, candidates, __event_emitter__)

    def _footer(self, category, tier, model) -> str:
        return (f"\n\n*Auto (Smart): routed to the {tier} {category} model `{model}`.*"
                if self.valves.SHOW_ROUTE else "")

    async def _complete(self, body, headers, url, category, tier, candidates, emitter) -> str:
        last_err = "no candidates"
        for model in candidates:
            await self._emit(emitter, f"Trying {tier} {category} model ({model})...")
            try:
                async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                    r = await client.post(url, json=self._payload(body, model), headers=headers)
                if r.status_code == 200:
                    content = (r.json()["choices"][0]["message"].get("content") or "").strip()
                    if content:
                        await self._emit(emitter, f"Answered by {model}", done=True)
                        return content + self._footer(category, tier, model)
                    last_err = f"{model} returned empty"
                else:
                    last_err = f"{model} -> {r.status_code}: {r.text[:120]}"
            except Exception as e:
                last_err = f"{model}: {e}"
        await self._emit(emitter, "All candidates were busy", done=True)
        return f"[auto-smart] every model was rate-limited or failed. Last: {last_err}. Try again."

    async def _stream(self, body, headers, url, category, tier, candidates,
                      emitter) -> AsyncIterator[str]:
        last_err = "no candidates"
        for model in candidates:
            await self._emit(emitter, f"Trying {tier} {category} model ({model})...")
            got_any = False
            try:
                async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                    async with client.stream("POST", url, json=self._payload(body, model),
                                             headers=headers) as r:
                        if r.status_code != 200:
                            detail = (await r.aread()).decode("utf-8", "replace")[:120]
                            last_err = f"{model} -> {r.status_code}: {detail}"
                            continue
                        async for line in r.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[len("data:"):].strip()
                            if data == "[DONE]":
                                break
                            try:
                                delta = json.loads(data)["choices"][0]["delta"].get("content")
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
                            if delta:
                                got_any = True
                                yield delta
            except Exception as e:
                last_err = f"{model}: {e}"
                if got_any:
                    return
                continue
            if got_any:
                await self._emit(emitter, f"Answered by {model}", done=True)
                footer = self._footer(category, tier, model)
                if footer:
                    yield footer
                return
            last_err = f"{model} returned empty"
        await self._emit(emitter, "All candidates were busy", done=True)
        yield f"\n\n[auto-smart] every model was rate-limited or failed. Last: {last_err}. Try again."
