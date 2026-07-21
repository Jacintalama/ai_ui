"""
title: Auto (Free)
author: Ralph Benitez
version: 1.0.0
description: One "Auto" model that reads your question and routes it to the best FREE model on OpenRouter - code questions to a code model, math and logic to a reasoning model, everything else to a general model. No paid model is ever used.
"""

# Why a pipe and not a LiteLLM container:
# the whole feature is ~60 lines of routing rules plus a call to OpenRouter.
# Running it as a pipe keeps it inside the Open WebUI process that is already up,
# so it costs no extra container and no extra RAM on a box that runs near its
# memory limit. A LiteLLM gateway would have added a 400MB container for the same
# result. The routing logic is kept in plain, tested functions (see
# tests/test_auto_router_pipe.py) so it can be verified without a key or network.

import json
import os
import re
from typing import Any, AsyncIterator, Callable, Optional, Union

import httpx
from pydantic import BaseModel, Field

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ---------------------------------------------------------------------------
# Routing rules (pure, no I/O, unit tested). pick_category returns one of
# "coder" / "reasoning" / "general"; the Pipe maps that to a real free model id
# via its Valves, so swapping a model is a settings change, not a code edit.
# ---------------------------------------------------------------------------
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


def _last_user_text(messages) -> str:
    """The most recent user turn's text. Multimodal turns arrive as a list of
    parts; join the text ones so a "refactor this" with an attached image still
    routes on its words."""
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
    """Distinct keywords present, matched on word boundaries so "api" does not
    fire on "apiece"."""
    hits = 0
    for kw in keywords:
        if kw.isalpha():
            if re.search(rf"\b{re.escape(kw)}\b", text):
                hits += 1
        elif kw in text:  # phrases ("step by step") and tokens ("c++")
            hits += 1
    return hits


def pick_category(messages) -> str:
    """Choose a route for a question. The category with the most keyword hits
    wins; a tie or no hits falls through to general. A code fence is treated as
    a strong code signal so a one-line snippet still routes to the coder."""
    text = _last_user_text(messages).lower()
    if not text.strip():
        return DEFAULT_CATEGORY
    scores = {cat: _score(text, kws) for cat, kws in RULES.items()}
    if "```" in text:
        scores["coder"] = scores.get("coder", 0) + 3
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else DEFAULT_CATEGORY


class Pipe:
    """The single "Auto (Free)" model. Reads the question, picks a free model,
    streams OpenRouter's answer back."""

    class Valves(BaseModel):
        OPENROUTER_API_KEY: str = Field(
            default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", ""),
            description="OpenRouter API key (free tier). Read from env by default.",
        )
        # Model ids are OpenRouter :free ids and DO rotate. If a route starts
        # failing, re-check https://openrouter.ai/api/v1/models and update here.
        MODEL_GENERAL: str = Field(
            default="openai/gpt-oss-20b:free",
            description="Free model for general questions.",
        )
        MODEL_CODER: str = Field(
            default="cohere/north-mini-code:free",
            description="Free model for code questions.",
        )
        MODEL_REASONING: str = Field(
            default="nvidia/nemotron-3-super-120b-a12b:free",
            description="Free model for math and logic questions.",
        )
        SHOW_ROUTE: bool = Field(
            default=True,
            description="Append a small note of which free model answered.",
        )
        TIMEOUT_SECONDS: int = Field(default=120, description="HTTP timeout.")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "auto", "name": "Auto (Free)"}]

    def _model_for(self, category: str) -> str:
        return {
            "coder": self.valves.MODEL_CODER,
            "reasoning": self.valves.MODEL_REASONING,
        }.get(category, self.valves.MODEL_GENERAL)

    def _payload(self, body: dict, model: str) -> dict:
        """Only forward fields OpenRouter accepts; Open WebUI adds extras
        (model name, user, metadata) that would be rejected."""
        out = {"model": model, "messages": body.get("messages") or []}
        for k in ("stream", "temperature", "top_p", "max_tokens",
                  "frequency_penalty", "presence_penalty", "stop"):
            if body.get(k) is not None:
                out[k] = body[k]
        return out

    async def _emit(self, emitter: Optional[Callable], description: str,
                    done: bool = False) -> None:
        if emitter:
            await emitter({"type": "status",
                           "data": {"description": description, "done": done}})

    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> Union[str, AsyncIterator[str]]:
        category = pick_category(body.get("messages") or [])
        model = self._model_for(category)
        key = self.valves.OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY", "")

        if not key:
            return ("Auto router is not configured: OPENROUTER_API_KEY is missing. "
                    "Add it to the environment or this function's valves.")
        if not (body.get("messages")):
            return "No message to answer."

        await self._emit(__event_emitter__,
                         f"Routing to a free {category} model ({model})...")

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Optional OpenRouter attribution headers.
            "HTTP-Referer": "https://ai-ui.coolestdomain.win",
            "X-Title": "AIUI Auto Router",
        }
        payload = self._payload(body, model)

        if payload.get("stream"):
            return self._stream(payload, headers, category, model, __event_emitter__)
        return await self._complete(payload, headers, category, model, __event_emitter__)

    def _footer(self, category: str, model: str) -> str:
        return (f"\n\n*Auto-routed to the free {category} model `{model}`.*"
                if self.valves.SHOW_ROUTE else "")

    async def _complete(self, payload, headers, category, model, emitter) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                r = await client.post(OPENROUTER_URL, json=payload, headers=headers)
                if r.status_code != 200:
                    await self._emit(emitter, "Auto router failed", done=True)
                    return f"[auto-router] OpenRouter error {r.status_code}: {r.text[:300]}"
                data = r.json()
                content = data["choices"][0]["message"].get("content") or ""
        except Exception as e:
            await self._emit(emitter, "Auto router failed", done=True)
            return f"[auto-router] request failed: {e}"
        await self._emit(emitter, f"Answered by {model}", done=True)
        return content + self._footer(category, model)

    async def _stream(self, payload, headers, category, model,
                      emitter) -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                async with client.stream("POST", OPENROUTER_URL, json=payload,
                                         headers=headers) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        await self._emit(emitter, "Auto router failed", done=True)
                        yield f"[auto-router] OpenRouter error {r.status_code}: {detail}"
                        return
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
                            yield delta
        except Exception as e:
            yield f"\n\n[auto-router] request failed: {e}"
            return
        await self._emit(emitter, f"Answered by {model}", done=True)
        footer = self._footer(category, model)
        if footer:
            yield footer
