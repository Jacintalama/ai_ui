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
import time
from typing import Any, AsyncIterator, Callable, Optional, Union

import httpx
from pydantic import BaseModel, Field

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

#: Only the pipe places a marker. This finds one shaped comment anywhere in
#: an agent's own words, so it can be stripped before a real marker is
#: appended, and the page never parses one the agent wrote by accident or by
#: prompt injection.
AIUI_TURNS_STRIP_RE = re.compile(r"<!--\s*aiui:turns\b[^>]*-->")

# ---------------------------------------------------------------------------
# Routing rules (pure, no I/O, unit tested). pick_category returns one of
# "coder" / "reasoning" / "general"; the Pipe maps that to a real free model id
# via its Valves, so swapping a model is a settings change, not a code edit.
# ---------------------------------------------------------------------------
DEFAULT_CATEGORY = "general"

# When the chosen free model is rate-limited (429) or errors, Auto retries these
# in order so a busy free provider never dead-ends the user.
#
# Every id here was measured against the live API on 2026-09-10: each one
# answered "what is 17 times 4" correctly, in the time noted. The previous pool
# listed openai/gpt-oss-20b:free and nvidia/nemotron-nano-9b-v2:free, both of
# which OpenRouter had withdrawn, and google/gemma-4-26b-a4b-it:free, which
# answers 429 on essentially every call. So three of four retries could not
# have worked no matter what was asked.
#
# Deliberately excluded, and why:
#   google/gemma-4-31b-it:free       answered once, then 429 on the next call
#   poolside/laguna-*:free           429
#   thinkingmachines/inkling*:free   403, not available on this account
#   nvidia/nemotron-3-ultra-*:free   timed out at 45s
#   nvidia/nemotron-3-nano-omni-*    returned a body with no choices
#   nvidia/nemotron-3.5-lightning    correct but 9.4s, too slow to wait on
FALLBACK_POOL = [
    "nex-agi/nex-n2.5-mini:free",              # 0.5s
    "inclusionai/ling-3.0-flash-fin:free",     # 0.8s
    "nvidia/nemotron-3-super-120b-a12b:free",  # 1.0s
    "nex-agi/nex-n2.5-pro:free",               # 1.3s
    "liquid/lfm-2.5-2.6b:free",                # 1.4s
]

#: OpenRouter's free ids rotate: a model that worked last month can be gone
#: today, and asking for a withdrawn id fails exactly like a rate limit. That
#: is what made this router look permanently broken rather than occasionally
#: busy, so the ids above are checked against what is actually being served
#: before any of them is tried. Fresh ids alone would have rotted the same way.
_MODELS_URL = "https://openrouter.ai/api/v1/models"
AVAILABLE_TTL_SECONDS = 900
_available_ids: set = set()
_available_at = 0.0


async def _available_models(key: str) -> set:
    """Model ids OpenRouter is serving right now, cached for a quarter hour.

    Fails OPEN, twice over: a fetch that errors returns whatever was cached
    before, and an empty result is never cached. A router that refuses to try
    anything because it could not read a catalogue is worse than one that
    tries an id that turns out to be gone.
    """
    global _available_ids, _available_at
    now = time.time()
    if _available_ids and now - _available_at < AVAILABLE_TTL_SECONDS:
        return _available_ids
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                _MODELS_URL, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            ids = {m.get("id") for m in (r.json().get("data") or []) if m.get("id")}
    except Exception:
        return _available_ids
    if ids:
        _available_ids = ids
        _available_at = now
    return _available_ids


def _keep_available(candidates: list, available: set) -> list:
    """The candidates OpenRouter still serves, in order.

    Never returns empty: if the catalogue says none of them exist, that is far
    more likely to mean the catalogue is wrong than that every model vanished,
    so the caller still gets its list and finds out by asking.
    """
    if not available:
        return candidates
    live = [m for m in candidates if m in available]
    return live or candidates

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
            # Was openai/gpt-oss-20b:free, which OpenRouter has withdrawn.
            # General is where most questions land, so this one id being dead
            # is most of why Auto (Free) failed. Measured at 0.5s and correct.
            default="nex-agi/nex-n2.5-mini:free",
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
        # Ralph's team is standardising on this model, so the agents have to
        # answer here too. The tasks service decides who is named or awake;
        # this pipe only asks, and only answers for itself when nobody is.
        TASKS_URL: str = Field(
            default_factory=lambda: os.environ.get("TASKS_URL", "http://tasks:8210"),
            description="The tasks service, which owns the agents.",
        )
        INTERNAL_SECRET: str = Field(
            default_factory=lambda: os.environ.get("INTERNAL_CALLBACK_SECRET", ""),
            description="Read from the environment by default.",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def _agents_first(self, body: dict, user_email: str) -> Optional[str]:
        """The rendered reply of whichever agents were named or awake, or
        None when nobody was and this pipe should answer as usual.

        route_only is what makes this safe to call from here: IO answers
        for itself THROUGH this pipe, so without it the service would ask
        IO, which would ask this pipe, which would ask the service. With
        it, an unnamed message gets an empty list back and falls through.

        Never raises. The agents are a bonus on top of a working free
        model, so a service outage costs the agents, never the answer.
        """
        if not user_email:
            return None
        chat_id = (body.get("chat_id")
                   or (body.get("metadata") or {}).get("chat_id")
                   or "web")
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                r = await client.post(
                    self.valves.TASKS_URL.rstrip("/") + "/agents/chat",
                    headers={"X-Internal-Secret": self.valves.INTERNAL_SECRET},
                    json={"user_email": user_email, "chat_id": chat_id,
                          "messages": body.get("messages") or [],
                          "route_only": True, "first_only": True})
                if r.status_code != 200:
                    return None
                data = r.json()
        except Exception:                                   # noqa: BLE001
            # Never the exception text: an httpx error carries the URL.
            return None
        data = data if isinstance(data, dict) else {}
        turns = data.get("turns")
        if not isinstance(turns, list) or not turns:
            return None
        rendered = data.get("rendered")
        if not (isinstance(rendered, str) and rendered.strip()):
            return None
        marker = data.get("marker")
        # Only the pipe places a marker. Anything marker shaped that arrived
        # inside an agent's own words is stripped first, so the page never
        # parses one the agent wrote rather than the one the service issued.
        rendered = AIUI_TURNS_STRIP_RE.sub("", rendered).rstrip()
        if isinstance(marker, str) and marker.strip():
            rendered = rendered.rstrip() + "\n\n" + marker.strip()
        return rendered

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

    def _candidates(self, category: str) -> list:
        """Primary model for the category, then reliable fallbacks, deduped."""
        out = [self._model_for(category)]
        for m in FALLBACK_POOL:
            if m not in out:
                out.append(m)
        return out

    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> Union[str, AsyncIterator[str]]:
        category = pick_category(body.get("messages") or [])
        key = self.valves.OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            return ("Auto router is not configured: OPENROUTER_API_KEY is missing. "
                    "Add it to the environment or this function's valves.")
        if not body.get("messages"):
            return "No message to answer."

        # An agent named or awake in this chat answers instead of a free
        # model, so "hi mia" reaches Mia here the same as it does on IO.
        agents = await self._agents_first(body, (__user__ or {}).get("email") or "")
        if agents is not None:
            return agents

        candidates = self._candidates(category)
        # Before spending a retry on it. A withdrawn id and a rate-limited one
        # fail identically from here, so without this the pool gets burned on
        # models that could not have answered whatever was asked.
        candidates = _keep_available(candidates, await _available_models(key))
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ai-ui.coolestdomain.win",
            "X-Title": "AIUI Auto Router",
        }
        if body.get("stream"):
            return self._stream(body, headers, category, candidates, __event_emitter__)
        return await self._complete(body, headers, category, candidates, __event_emitter__)

    def _footer(self, category: str, model: str) -> str:
        return (f"\n\n*Auto-routed to the free {category} model `{model}`.*"
                if self.valves.SHOW_ROUTE else "")

    async def _complete(self, body, headers, category, candidates, emitter) -> str:
        last_err = "no candidates"
        for model in candidates:
            await self._emit(emitter, f"Trying free {category} model ({model})...")
            try:
                async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                    r = await client.post(OPENROUTER_URL, json=self._payload(body, model),
                                          headers=headers)
                if r.status_code == 200:
                    content = (r.json()["choices"][0]["message"].get("content") or "").strip()
                    if content:
                        await self._emit(emitter, f"Answered by {model}", done=True)
                        return content + self._footer(category, model)
                    last_err = f"{model} returned empty"
                else:
                    last_err = f"{model} -> {r.status_code}: {r.text[:120]}"
            except Exception as e:
                last_err = f"{model}: {e}"
        await self._emit(emitter, "All free models were busy", done=True)
        return ("[auto-router] every free model was rate-limited or failed. "
                f"Last: {last_err}. Try again in a moment.")

    async def _stream(self, body, headers, category, candidates,
                      emitter) -> AsyncIterator[str]:
        last_err = "no candidates"
        for model in candidates:
            await self._emit(emitter, f"Trying free {category} model ({model})...")
            got_any = False
            try:
                async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                    async with client.stream("POST", OPENROUTER_URL,
                                             json=self._payload(body, model),
                                             headers=headers) as r:
                        if r.status_code != 200:
                            detail = (await r.aread()).decode("utf-8", "replace")[:120]
                            last_err = f"{model} -> {r.status_code}: {detail}"
                            continue  # rate-limited/error: try the next model
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
                    return  # already streamed partial content; cannot fall back
                continue
            if got_any:
                await self._emit(emitter, f"Answered by {model}", done=True)
                footer = self._footer(category, model)
                if footer:
                    yield footer
                return
            last_err = f"{model} returned empty"  # 200 but nothing: try next
        await self._emit(emitter, "All free models were busy", done=True)
        yield ("\n\n[auto-router] every free model was rate-limited or failed. "
               f"Last: {last_err}. Try again in a moment.")
