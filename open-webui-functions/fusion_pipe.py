"""
title: Fusion
author: Ralph Benitez
version: 2.0.0
description: Select Fusion and ask once. It queries several models, reads all their answers, and writes one merged, accurate, well-structured answer. Choose which models to fuse and the judge in this model's settings.
"""

# Why a pipe (a selectable model), not the toggle:
# Open WebUI runs after-response filters once PER model, and each run only sees
# one linear conversation branch, never the other selected models' answers
# (verified in middleware.outlet_filter_handler -> get_message_list). So a
# toggle can't read "all selected models" at once. A pipe can: it fans the
# question out to its own panel, gets every answer, and a judge merges them.
# All the heavy lifting stays in the tasks service's fusion engine; this pipe
# just streams the merged result.

import os
from typing import Any, AsyncIterator, Callable, Optional, Union

import httpx

TASKS_URL = os.environ.get("TASKS_URL", "http://tasks:8210")
INTERNAL_SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")


class Pipe:
    class Valves:
        pass

    class UserValves:
        pass

    def __init__(self):
        # Plain attributes (no pydantic needed): read from env, overridable via
        # the model's admin settings if wired later.
        self.tasks_url = TASKS_URL
        self.timeout_seconds = 300
        # Which models to fuse (from the fusion registry) and who judges. The
        # registry is paid models (OpenAI + Anthropic); a 2-provider panel gives
        # the most useful cross-check.
        self.panel = ["gpt-5.5", "claude-opus-4-8"]
        self.judge = "claude-opus-4-8"

    def pipes(self) -> list:
        return [{"id": "fusion", "name": "Fusion"}]

    def _prompt_messages(self, messages: list) -> list:
        """Conversation up to and including the last user turn (drop any trailing
        assistant reply) so the panel answers the question fresh."""
        out = []
        for m in messages or []:
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                out.append({"role": role, "content": content})
        while out and out[-1].get("role") == "assistant":
            out.pop()
        return out

    async def _emit(self, emitter, desc, done=False):
        if emitter:
            await emitter({"type": "status", "data": {"description": desc, "done": done}})

    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> Union[str, AsyncIterator[str]]:
        messages = self._prompt_messages(body.get("messages") or [])
        if not messages:
            return "No message to answer."
        if not INTERNAL_SECRET:
            return ("Fusion is not configured: INTERNAL_CALLBACK_SECRET is missing "
                    "from Open WebUI's environment.")
        panel = [m for m in (self.panel or []) if m]
        if not panel or not self.judge:
            return "Fusion has no panel or judge configured."

        await self._emit(__event_emitter__,
                         f"Fusing {len(panel)} models: {', '.join(panel)}...")
        return self._stream(messages, panel, __event_emitter__)

    async def _stream(self, messages, panel, emitter) -> AsyncIterator[str]:
        url = self.tasks_url.rstrip("/") + "/api/fusion/complete"
        payload = {"messages": messages, "panel": panel, "judge": self.judge}
        got_any = False
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream(
                    "POST", url, json=payload,
                    headers={"X-Internal-Secret": INTERNAL_SECRET},
                ) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        await self._emit(emitter, "Fusion failed", done=True)
                        yield f"[fusion] failed ({r.status_code}): {detail}"
                        return
                    async for piece in r.aiter_text():
                        if piece:
                            got_any = True
                            yield piece
        except Exception as e:
            yield f"\n\n[fusion] could not run: {e}"
            return
        await self._emit(emitter,
                         f"Fused {len(panel)} models" if got_any else "Fusion returned nothing",
                         done=True)
