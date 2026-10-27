"""The main chat's own assistant (2026-10-27).

Lukas, standup 2026-10-27: "control everything from the main chat", "I
don't need to be selecting the MCP service ... it just discovers them when
it needs them", "build me a team of agents and it would know how to do it".

Everyone's default model is Auto (Free). Until now a message no agent took
went from the Auto pipe to a free OpenRouter model with no tools at all, so
the main chat could not read a calendar, a mailbox, a Drive or a month-old
meeting. Now /agents/chat answers it with this assistant instead: our own
tool loop, with the tools Jev picks for the message (agent_jev.pick_tools),
memory, the knowledge graph block, skills, cost rows, and the access level
that asks Yes/No before anything that sends, creates or changes.

It is a virtual agent, not a row in Open WebUI: routes_agent_turn
._resolve_agent_row knows its id. Its base is the IO pipe and its model is
in meta.llm (agent_llm, 2026-10-27), so the runner posts the free model
directly and never the pipe, which would ask this service again.
Design: docs/plans/2026-10-27-main-chat-finds-its-tools.md.
"""
from __future__ import annotations

import agent_access
import agent_llm

ASSISTANT_ID = "io-assistant"
NAME = "IO"

SYSTEM = (
    "You are IO, the assistant in this person's main chat. You can use the "
    "tools you are given to read their email, calendar, files, apps, "
    "connected services and past conversations, and to make AI agents for "
    "them. Use a tool whenever the answer depends on their own things "
    "rather than guessing. Anything that sends, creates, deletes or changes "
    "something is shown to them to approve first, so ask for it plainly and "
    "say what you will do. Keep answers short and plain.")


def is_assistant(agent_id) -> bool:
    return agent_id == ASSISTANT_ID


def _model() -> str:
    """The head of the agents' free pool, read late so a test or a compose
    change to the pool is honoured. Empty when the pool is empty, which
    agent_llm reads as an assistant that cannot run."""
    import agent_runner
    pool = agent_runner.FREE_MODELS
    return pool[0] if pool else ""


def agent() -> dict:
    """The assistant as the agent row the runner, the brief and the memory
    read."""
    meta = {"access": agent_access.MODE_ASK,
            "description": "The main chat's assistant"}
    model = _model()
    if model:
        meta["llm"] = model
    return {"id": ASSISTANT_ID, "name": NAME,
            "base_model_id": agent_llm.base_model(),
            "meta": meta, "params": {"system": SYSTEM}}
