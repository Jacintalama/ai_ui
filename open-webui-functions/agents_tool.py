"""
title: Ask Your Agents
author: Ralph Benitez
version: 1.0.0
description: Lets any tool capable model reach the user's own AI agents by name, or all of them at once, without switching to the IO model first.
requirements: httpx
"""
# Today an agent only answers when the person has selected the IO pipe as
# their model (open-webui-functions/io_gateway_pipe.py). This tool is the
# same seam, offered to every other model instead: it asks the tasks service
# who should answer and hands back what they said, so a name like "hi mia"
# works no matter which model is selected.
#
# It holds NO routing logic on purpose, same as the pipe. The tasks service
# decides who answers, which is what keeps Discord, Telegram, the web chat
# and this tool all deciding it the same way, and what makes an agent's own
# access level (read only, full) apply here too: this call runs the real
# tool loop in the tasks service rather than the caller's own.
import os

import httpx
from pydantic import BaseModel, Field

#: Shown when a turn's answer came back empty. Mirrors EMPTY in
#: io_gateway_pipe.py so the same situation reads the same way in both
#: places, without importing across the process boundary to get it.
EMPTY_TURN = "There was nothing to answer."

#: The first line of a successful reply, so the calling model does not
#: paraphrase an agent's own words into something the agent never said.
RELAY_INSTRUCTION = ("Relay each agent's answer to the user exactly as "
                     "written below. Do not summarize or paraphrase it.")

#: Appended to the user's email to make a chat id, because this tool is
#: never given the conversation's real chat id, only the message text. A
#: fixed suffix keeps that id STABLE across turns of the same conversation
#: on this path, so an agent named once stays pinned for a follow up with no
#: name in it, the same way the web chat pin behaves.
CHAT_ID_SUFFIX = "::any-model-tool"


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        internal_secret: str = Field(
            default=os.environ.get("INTERNAL_CALLBACK_SECRET", ""))
        timeout_seconds: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    def _render_turn(self, turn: dict) -> str:
        """One turn, on its own. Same shape as io_gateway_pipe.py's
        _render_turn: a turn with no agent gets no name prefix, and notes
        ride along after the answer."""
        agent = turn.get("agent")
        agent = agent if isinstance(agent, dict) else None

        if agent is None:
            return (turn.get("answer") or "").strip() or EMPTY_TURN

        name = agent.get("name") or agent.get("id") or "Agent"
        answer = (turn.get("answer") or "").strip()
        notes = [n for n in (turn.get("notes") or []) if isinstance(n, str)]
        if notes:
            note_text = "\n".join(notes)
            answer = (answer + "\n\n" + note_text) if answer else note_text
        answer = answer or EMPTY_TURN
        return "%s:\n%s" % (name, answer)

    async def ask_agents(self, message: str, __user__: dict = {}) -> str:
        """
        Call this when the user's message addresses one of their AI agents
        by name (for example "hi mia, are you there" or "ada, check my
        inbox"), or addresses all of them at once with a word like "team",
        "everyone", "all of you" or "guys". Do not call this for a message
        that is not directed at an agent.

        Pass the user's message to this tool as-is, unedited, so the agent
        sees exactly what the person typed rather than a rewritten version
        of it.
        """
        email = (__user__ or {}).get("email") or ""
        if not email:
            return ("I could not tell whose account this is, so I did not "
                    "reach any agent.")
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                r = await c.post(
                    self.valves.tasks_url.rstrip("/") + "/agents/chat",
                    headers={"X-Internal-Secret": self.valves.internal_secret},
                    json={"user_email": email,
                         "chat_id": email + CHAT_ID_SUFFIX,
                         "messages": [{"role": "user", "content": message}]})
                r.raise_for_status()
                data = r.json()

            # Comes over HTTP from another service, so the shape is not ours
            # to trust: normalise before reading anything off it, the same
            # way io_gateway_pipe.py's _render does. This must stay inside
            # the try, not just the request itself, or a malformed but
            # successful response still raises past the guard below.
            data = data if isinstance(data, dict) else {}
            turns = data.get("turns")
            turns = turns if isinstance(turns, list) else []
            turns = [t for t in turns if isinstance(t, dict)]

            if not turns:
                return "None of your agents had anything to say."

            rendered = "\n\n".join(self._render_turn(t) for t in turns)
            return RELAY_INSTRUCTION + "\n\n" + rendered
        except Exception:                                   # noqa: BLE001
            # Never include the exception text: an httpx error carries the
            # request URL, and this project has already leaked a token that way.
            return ("I could not reach your agents just now. Try again in "
                    "a moment.")
