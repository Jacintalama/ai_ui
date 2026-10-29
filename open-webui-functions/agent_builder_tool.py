"""
title: Agent Builder
author: Ralph Benitez
version: 1.0.0
description: Make your own AI agents from the chat: create an agent, or list the ones you have.
requirements: httpx
"""
# This tool holds no secret, deliberately, the way schedules_tool.py does:
# it sends the caller's email and nothing else, and every route it calls on
# the tasks service is scoped to that email. A model cannot name the user,
# so it cannot act as another one.
import os

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------ plumbing

    def _email(self, __user__: dict) -> str:
        user = __user__ if isinstance(__user__, dict) else {}
        return str(user.get("email") or "").strip()

    async def _call(self, method: str, path: str, email: str, json_body: dict = None):
        """One request as this person. Returns (ok, data) or (False, sentence).
        Never raises and never includes the exception text."""
        url = self.valves.tasks_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.request(method, url, headers={"X-User-Email": email}, json=json_body)
                if not response.is_success:
                    return False, self._refusal(response)
                return True, (response.json() if response.content else {})
        except Exception:                                   # noqa: BLE001
            return False, "I could not reach your agents just now."

    def _refusal(self, response) -> str:
        if response.status_code < 500:
            try:
                detail = response.json().get("detail")
            except Exception:                               # noqa: BLE001
                detail = None
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return "I could not reach your agents just now."

    async def _roster(self, email: str):
        ok, data = await self._call("GET", "/agents/roster", email)
        if not ok:
            return None, data
        return [a for a in (data.get("agents") or []) if isinstance(a, dict)], ""

    def _find(self, agents: list, name: str):
        want = (name or "").strip().lower()
        for a in agents:
            if str(a.get("name") or "").lower() == want or str(a.get("id") or "").lower() == want:
                return a
        return None

    # --------------------------------------------------------------------- tools

    async def list_my_agents(self, __user__: dict = {}) -> str:
        """List the agents this person already has, with their roles. Use this
        before creating one, so you do not make a second Mia."""
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot list your agents."
        agents, why = await self._roster(email)
        if agents is None:
            return why
        if not agents:
            return "You have no agents yet. I can make one: give me a name and what it should do."
        return "Your agents: " + "; ".join(
            a["name"] + (" (" + a["role"] + ")" if a.get("role") else "") for a in agents) + "."

    async def create_agent(self, name: str, instructions: str, role: str = "",
                           access: str = "read", confirm: str = "",
                           __user__: dict = {}) -> str:
        """Create a new AI agent for this person, in TWO steps.

        Call it WITHOUT `confirm` first. Nothing is created: you get back the
        agent exactly as it would be, including its full instructions, and
        you must show that to the person word for word and ask whether to go
        ahead. Do not summarise the instructions; they are what the agent
        will be, and the person is approving them.

        Only once they have seen it and agreed, call again with the SAME
        name, instructions, role and access plus the `confirm` code that came
        back. Changing any wording invalidates the code on purpose, and you
        will get a fresh preview to show them instead.

        `name` is one word (Jack, Mia). `instructions` is what it does and how
        it answers, in plain sentences. `role` is two or three words shown on
        its card (Project manager). `access` is read (looks things up,
        changes nothing), ask (can act but asks first) or all (acts without
        asking); use read unless the person asked for more.
        """
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot make an agent."
        ok, data = await self._call("POST", "/agents/make", email, {
            "name": (name or "").strip(), "instructions": (instructions or "").strip(),
            "role": (role or "").strip(), "access": (access or "read").strip().lower(),
            "confirm": (confirm or "").strip()})
        if not ok:
            return data
        # The service decides whether this was a preview or a create, and it
        # enforces it: a confirm code it has not issued does not create
        # anything. So the tool reports what happened rather than assuming.
        if not data.get("created", True):
            return data.get("message") or "Nothing was created yet."
        words = {"read": "read only", "ask": "with access, asking first", "all": "all access"}
        return ("Made " + data.get("name", name) + (" (" + data["role"] + ")" if data.get("role") else "") +
                ", " + words.get(data.get("access"), "read only") +
                ". It is in the Agent Office now, in the room of its tools.")
