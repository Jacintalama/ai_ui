"""
title: Knowledge Graph Memory
author: Ralph Benitez
version: 0.1.0
description: Injects your personal knowledge-graph memory into every chat, so any model you pick remembers the topics and projects you work on. Private to your account.
"""

# Global inlet filter. Runs BEFORE the model on every chat (no toggle, no tool
# call needed), so it works for every model. It asks the tasks service for the
# signed-in user's own knowledge-graph context relevant to their latest
# message, then inserts that as a system message. Strictly per-user (keyed by
# __user__.email). Fails open: any error just leaves the chat untouched.
#
# Note: inlet modifies the request only; it does not persist to chat history,
# so each turn gets fresh, message-relevant memory rather than a growing block.

from typing import Optional

import httpx
from pydantic import BaseModel, Field

# Marker phrase present in every context block we inject, used to avoid
# double-injecting within a single request.
_MEMORY_MARKER = "personal knowledge graph"


class Filter:
    class Valves(BaseModel):
        tasks_url: str = Field(default="http://tasks:8210")
        max_items: int = Field(default=6)
        timeout_seconds: int = Field(default=6)
        min_query_chars: int = Field(default=3)

    def __init__(self):
        self.valves = self.Valves()

    # --- pure helpers -----------------------------------------------------
    def _last_user_text(self, body: dict) -> str:
        for m in reversed(body.get("messages") or []):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return " ".join(
                        p.get("text", "") for p in c
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
        return ""

    def _already_injected(self, messages: list) -> bool:
        for m in messages:
            if (isinstance(m, dict) and m.get("role") == "system"
                    and _MEMORY_MARKER in (m.get("content") or "").lower()):
                return True
        return False

    def _insert_index(self, messages: list) -> int:
        """Insert right after any leading system prompt(s), before user turns."""
        idx = 0
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system":
                idx += 1
            else:
                break
        return idx

    # --- I/O --------------------------------------------------------------
    async def _fetch_context(self, user_email: str, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                r = await client.get(
                    f"{self.valves.tasks_url}/graph/mine/context",
                    params={"q": query, "limit": self.valves.max_items},
                    headers={"X-User-Email": user_email},
                )
            if r.status_code == 200:
                return (r.json() or {}).get("context") or ""
        except Exception as e:
            print(f"[kg_memory] fetch error: {e}", flush=True)
        return ""

    # --- OWUI hook --------------------------------------------------------
    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        try:
            user_email = (__user__ or {}).get("email") or ""
            if not user_email:
                return body
            messages = body.get("messages") or []
            if self._already_injected(messages):
                return body
            query = self._last_user_text(body)
            if len((query or "").strip()) < self.valves.min_query_chars:
                return body
            ctx = await self._fetch_context(user_email, query)
            if not ctx:
                return body
            messages.insert(self._insert_index(messages),
                            {"role": "system", "content": ctx})
            body["messages"] = messages
            print(f"[kg_memory] injected context for {user_email} "
                  f"({len(ctx)} chars)", flush=True)
        except Exception as e:
            print(f"[kg_memory] inlet error: {e}", flush=True)
        return body
