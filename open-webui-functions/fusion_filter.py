"""
title: Fusion
author: Ralph Benitez
version: 1.0.0
description: Toggle on. Your model answers first, then Fusion cross-checks the question across a panel of models and appends one verified answer that names where they disagree. Pick the panel and judge in this filter's settings.
"""

# Why a toggleable filter (not a tool, not just the Fuse action):
# a filter can set self.toggle = True, which Open WebUI renders as an on/off
# switch in the composer - the discoverable control that was wanted. Tools were
# ruled out because they need function-calling, which some models reject. The
# Fuse action still exists as a per-answer button; this adds the toggle on top.
#
# Behaviour honours "fusion runs AFTER the models answer": the selected model's
# reply streams first, then outlet() fans the same question out to the fusion
# panel and judge (tasks /api/fusion/complete) and appends the verified answer.

import os
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, Field

TASKS_URL = os.environ.get("TASKS_URL", "http://tasks:8210")
INTERNAL_SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")

# Small purple sparkle so the toggle is recognisable in the composer.
ICON = (
    "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmci"
    "IHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjI0IiBoZWlnaHQ9IjI0Ij48cGF0aCBmaWxsPSIjN0Mz"
    "QUVEIiBkPSJNMTIgMmwyIDcgNyAxLjUtNyAxLjUtMiA3LTItNy03LTEuNSA3LTEuNXoiLz48L3N2Zz4="
)


class Filter:
    class Valves(BaseModel):
        tasks_url: str = Field(
            default=TASKS_URL,
            description="Base URL of the tasks service on the docker network.",
        )
        timeout_seconds: int = Field(
            default=300, description="How long to wait for the fusion."
        )

    class UserValves(BaseModel):
        panel: str = Field(
            default="claude-opus-4-8,gpt-5.5",
            description="Comma-separated models to cross-check (from the fusion registry).",
        )
        judge: str = Field(
            default="claude-opus-4-8",
            description="Model that reads the panel answers and writes the verified one.",
        )

    def __init__(self):
        self.valves = self.Valves()
        # These two lines make Open WebUI render this as a toggle in the composer.
        self.toggle = True
        self.icon = ICON

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        # Nothing to change on the way in; the selected model answers normally.
        return body

    def _prompt_messages(self, messages: list) -> list:
        """The conversation up to and including the last user turn, so the panel
        answers the user's question rather than re-reading the assistant's reply."""
        out = []
        for m in messages:
            role = m.get("role")
            content = m.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            out.append({"role": role, "content": content})
        # Drop any trailing assistant turns (the just-generated reply).
        while out and out[-1].get("role") == "assistant":
            out.pop()
        return out

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> dict:
        async def say(desc: str, done: bool = False) -> None:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": desc, "done": done}}
                )

        async def post(md: str) -> None:
            if __event_emitter__:
                await __event_emitter__({"type": "message", "data": {"content": md}})

        messages = self._prompt_messages(body.get("messages") or [])
        if not messages:
            return body
        if not INTERNAL_SECRET:
            await post("\n\n---\n**Fusion:** not configured (INTERNAL_CALLBACK_SECRET "
                       "missing from Open WebUI's environment).\n")
            return body

        uv = (__user__ or {}).get("valves") or self.UserValves()
        panel = [m.strip() for m in (uv.panel or "").split(",") if m.strip()]
        judge = (uv.judge or "").strip()
        if not panel or not judge:
            await post("\n\n---\n**Fusion:** set a panel and a judge in the filter "
                       "settings.\n")
            return body

        await say(f"Fusion: cross-checking with {', '.join(panel)}...")
        url = self.valves.tasks_url.rstrip("/") + "/api/fusion/complete"
        payload = {"messages": messages, "panel": panel, "judge": judge}
        chunks: list = []
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                async with client.stream(
                    "POST", url, json=payload,
                    headers={"X-Internal-Secret": INTERNAL_SECRET},
                ) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        await say("Fusion failed", done=True)
                        await post(f"\n\n---\n**Fusion failed** ({r.status_code}): {detail}\n")
                        return body
                    async for piece in r.aiter_text():
                        if piece:
                            chunks.append(piece)
        except Exception as e:
            await say("Fusion failed", done=True)
            await post(f"\n\n---\n**Fusion could not run:** {e}\n")
            return body

        verified = "".join(chunks).strip()
        if not verified:
            await say("Fusion returned nothing", done=True)
            return body

        await say(f"Fusion: cross-checked {len(panel)} models", done=True)
        await post(f"\n\n---\n## Fusion (verified)\n\n{verified}\n\n"
                   f"*Cross-checked {', '.join(panel)}; fused by {judge}.*\n")
        return body
