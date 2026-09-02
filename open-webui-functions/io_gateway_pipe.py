"""
title: IO
id: io
description: Talks to you, and wakes one of your agents when you name it.
author: Ralph Benitez
version: 1.0.0
requirements: httpx
"""
# The gateway model. Say "hi mia" and Mia answers; say nothing in particular
# and IO answers.
#
# It holds NO routing logic on purpose. The tasks service decides who should
# answer, which keeps one implementation serving Discord, Telegram and this
# chat, and means an agent used here runs through the same tool loop as
# everywhere else. That is what makes the per-agent access levels apply in the
# web chat: Open WebUI's own loop never reaches our code, so without this an
# agent set to Read only would still write.
import json
import os
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, Field

TASKS_URL = os.environ.get("TASKS_URL", "http://tasks:8210")
INTERNAL_SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")

#: Long enough for three rounds of tool use plus the tool calls themselves,
#: matching the channel budget in agent_runner. A timeout here reads to the
#: person as the model ignoring them.
TIMEOUT_SECONDS = 420.0

NO_USER = ("I could not tell whose account this is, so I did not run anything. "
           "Sign out and back in, and try again.")
TASKS_DOWN = ("I could not reach my memory just now, so I could not check your "
              "agents. Try again in a moment.")
EMPTY = "There was nothing to answer."

#: One argument value in an approval question. Enough to recognise a
#: recipient or a subject, not enough for a message body to bury the question.
MAX_ARG_CHARS = 120
MAX_ARGS_SHOWN = 5


class Pipe:
    class Valves(BaseModel):
        TASKS_URL: str = Field(
            default=TASKS_URL, description="Base URL of the tasks service.")
        INTERNAL_SECRET: str = Field(
            default=INTERNAL_SECRET,
            description="Shared secret for the tasks service. Read from env.")
        SHOW_AGENT_NAME: bool = Field(
            default=True,
            description="Prefix an agent's answer with its name.")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "io", "name": "IO"}]

    # --- talking to the tasks service -------------------------------------

    async def _ask_tasks(self, user_email: str, chat_id: str,
                         messages: list) -> dict:
        """Who should answer, and their answer if it is an agent."""
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            r = await client.post(
                self.valves.TASKS_URL.rstrip("/") + "/agents/chat",
                headers={"X-Internal-Secret": self.valves.INTERNAL_SECRET},
                json={"user_email": user_email, "chat_id": chat_id,
                      "messages": messages})
            r.raise_for_status()
            return r.json()

    # --- rendering ---------------------------------------------------------

    def _approval_question(self, agent_name: str, calls: list) -> str:
        """What the agent wants to do, in its own terms.

        The tool's own name and arguments, not a hand written phrase per tool.
        A phrasebook covering 300+ tools would be wrong somewhere, and where it
        was wrong is exactly where somebody would approve the wrong thing.
        """
        lines = ["%s wants to run:" % (agent_name or "This agent")]
        for call in calls or []:
            call = call if isinstance(call, dict) else {}
            fn = call.get("function")
            fn = fn if isinstance(fn, dict) else {}
            name = fn.get("name")
            name = name.strip() if isinstance(name, str) and name.strip() else "an unnamed tool"
            lines.append("  " + name)
            raw = fn.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (ValueError, TypeError):
                args = {}
            if isinstance(args, dict):
                for k, v in list(args.items())[:MAX_ARGS_SHOWN]:
                    lines.append("     %s: %s" % (k, str(v)[:MAX_ARG_CHARS]))
        if len(lines) == 1:
            lines.append("  something it did not name")
        lines.append("")
        lines.append("Reply yes to let it, or no to skip.")
        return "\n".join(lines)

    def _render_turn(self, turn: dict) -> str:
        """One turn, on its own. Same rules the single-turn shape always
        used: a pending turn asks its approval question, a turn with no
        agent gets no name prefix, and notes ride along after the answer.
        """
        agent = turn.get("agent")
        agent = agent if isinstance(agent, dict) else None

        if agent is None:
            # IO answered for itself. Prefixing a name here would invent a
            # speaker who was never involved.
            return (turn.get("answer") or "").strip() or EMPTY

        name = agent.get("name") or agent.get("id") or "Agent"

        pending = turn.get("pending")
        if isinstance(pending, dict) and pending.get("calls"):
            return self._approval_question(name, pending["calls"])

        answer = (turn.get("answer") or "").strip()
        notes = [n for n in (turn.get("notes") or []) if isinstance(n, str)]
        if notes:
            note_text = "\n".join(notes)
            answer = (answer + "\n\n" + note_text) if answer else note_text
        answer = answer or EMPTY
        if self.valves.SHOW_AGENT_NAME:
            return "%s:\n%s" % (name, answer)
        return answer

    def _render(self, out) -> str:
        # Comes over HTTP from another service, so the shape is not ours to
        # trust. _approval_question and _render_turn above are defensive for
        # the same reason.
        out = out if isinstance(out, dict) else {}
        turns = out.get("turns")
        turns = turns if isinstance(turns, list) else []
        turns = [t for t in turns if isinstance(t, dict)]
        if not turns:
            return EMPTY
        return "\n\n".join(self._render_turn(t) for t in turns)

    # --- the entry point ---------------------------------------------------

    async def pipe(self, body: dict, __user__: dict = None,
                   __event_emitter__: Optional[Callable[[dict], Any]] = None):
        """One message in, one answer out.

        Every exit returns a sentence. Somebody is watching this chat, so a
        silent failure is the one outcome that is never acceptable.
        """
        user_email = (__user__ or {}).get("email") or ""
        if not user_email:
            return NO_USER
        if not (body.get("messages") or []):
            return EMPTY

        chat_id = (body.get("chat_id")
                   or (body.get("metadata") or {}).get("chat_id")
                   or "web")

        try:
            out = await self._ask_tasks(user_email, chat_id,
                                        body.get("messages") or [])
        except Exception:                                   # noqa: BLE001
            # Never include the exception text: an httpx error can carry the
            # request URL, and this project has already leaked a token that way.
            return TASKS_DOWN

        try:
            return self._render(out)
        except Exception:                               # noqa: BLE001
            # Never let a shape we did not expect turn into a framework error
            # in somebody's chat window.
            return TASKS_DOWN
