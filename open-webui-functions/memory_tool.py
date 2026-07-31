"""
title: Remember
author: AIUI Team
version: 0.1.0
description: Let the assistant remember facts about you permanently. Say "remember that ..." and it's saved to your personal memory, appears in your Brain graph, and is used by every model in future chats.
"""

# Native Open WebUI tool. Writes to OWUI's own public.memory table via the
# tasks service, so the fact immediately shows up in (1) the Brain graph's
# Saved Memories hub, (2) the AI-memory context injected into every chat,
# and (3) Settings > Personalization > Memories where the user can edit or
# delete it.

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default="http://tasks:8210")
        timeout_seconds: int = Field(default=20)

    def __init__(self):
        self.valves = self.Valves()

    async def remember(self, fact: str, __user__: dict = {}) -> str:
        """
        Permanently remember a fact about the user. Use whenever the user says
        "remember that...", "don't forget...", "keep in mind...", or states a
        lasting preference or fact about themselves worth keeping. Phrase the
        fact in third person, short and specific (e.g. "Prefers replies in
        Tagalog", "Works as a nurse in Cebu").

        :param fact: The single fact to store, one sentence.
        :return: Confirmation to relay to the user, or an error sentence.
        """
        email = (__user__ or {}).get("email", "default@local")
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                r = await c.post(
                    f"{self.valves.tasks_url}/graph/mine/memory",
                    json={"content": fact},
                    headers={"X-User-Email": email},
                )
        except Exception as e:
            return f"Sorry, I could not save that right now: {e}"
        if r.status_code != 200:
            try:
                detail = r.json().get("detail", "")
            except Exception:
                detail = r.text[:120]
            return f"Sorry, I could not save that. {detail}"
        d = r.json()
        return (f"Saved to your memory: \"{d['content']}\" "
                f"(you now have {d['total_memories']} saved "
                f"{'memory' if d['total_memories'] == 1 else 'memories'}; "
                "view or edit them in Settings > Personalization > Memories, "
                "or see them in your Brain graph).")
