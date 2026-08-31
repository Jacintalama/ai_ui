"""One agent turn, run for the chat gateway.

The gateway holds the conversation and delivers the words. This holds the
tool loop, because the loop is where is_write_tool lives and that is the one
function deciding whether an agent may delete somebody's data. A second copy
of it in webhook-handler would be a second copy that can drift.

Deliberately internal only, and deliberately NOT part of routes_agents: that
router is mounted twice, bare and under /api/tasks, and the web mount is a
path an ordinary signed-in browser reaches. This one is mounted once.

The caller names the agent. It does not name the tools. tool_ids is the gate
on which native tools may execute (see execute_tool_call), so resolving it
here rather than accepting it is the difference between a permission and a
suggestion.
"""
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import agent_access
import agent_activity
from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                          CHANNEL_MAX_TOOL_ITERATIONS,
                          CHAT_TOKEN_TTL_SECONDS, _chat, _list_agents,
                          _owui_user_id_for)
from agent_tools import execute_tool_call
from owui_token import mint_owui_token
from routes_gateway import _require_internal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents")

#: A held conversation carries every tool result from its turn and lands in a
#: JSON column in the state store, so it is capped before it is handed back
#: for storage. Smaller than the loop's own excerpt cap because this one is
#: written to a row rather than passed along in memory.
PENDING_CONTENT_CHARS = 2000

#: A run that stopped to ask is neither finished nor still working. Recorded
#: as its own status so the card does not claim the agent is awake for the
#: next 45 minutes waiting for a reply that may never come.
STATUS_WAITING = "waiting"


class TurnIn(BaseModel):
    user_email: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    messages: list[dict]


class ResumeIn(BaseModel):
    user_email: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    conversation: list[dict]
    calls: list[dict]
    approved: bool


async def _resolve_agent(user_email: str, agent_id: str) -> tuple[str, list[str], str | None]:
    """(token, the agent's own tool ids, its access level).

    Raises HTTPException rather than returning a sentinel: every caller here
    would have to re-raise anyway, and a sentinel that got ignored once would
    run a turn with no tools and look like a model problem.
    """
    owner = await _owui_user_id_for(user_email)
    if not owner:
        raise HTTPException(status_code=404,
                            detail="no account for that user")
    token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)
    agents, truncated = await _list_agents(token)
    agent = next((a for a in agents
                  if isinstance(a, dict) and a.get("id") == agent_id), None)
    if agent is None:
        if truncated:
            # "Not in what we fetched" is not "does not exist". The listing
            # stopped early, so the agent may be on a page never reached.
            raise HTTPException(
                status_code=503,
                detail="could not check that agent just now")
        raise HTTPException(status_code=404, detail="no such agent")
    meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
    tools = meta.get("toolIds")
    tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []
    return token, tools, agent_access.level_of(meta)


def _trim_for_storage(conversation: list[dict]) -> list[dict]:
    """Cap what goes into the state store, without dropping any message.

    Dropping a message would break the turn: every tool_call in the assistant
    message needs a matching tool message before the next completion. So the
    contents shrink and the shape stays.
    """
    out = []
    for msg in conversation:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and len(content) > PENDING_CONTENT_CHARS:
            msg = dict(msg)
            msg["content"] = (content[:PENDING_CONTENT_CHARS]
                              + "\n\n[shortened]")
        out.append(msg)
    return out


def _pending_payload(user_email: str, agent_id: str,
                     err: agent_access.ApprovalRequired) -> dict:
    return {"pending": {
        "agent_id": agent_id,
        # Carried so the resume can check the person answering is the person
        # who was asked: the gateway's state key is per chat, not per person.
        "user_email": user_email,
        "calls": err.calls,
        "conversation": _trim_for_storage(err.conversation),
    }}


@router.post("/turn")
async def turn(body: TurnIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Run one turn as this user's agent, tools and all."""
    _require_internal(x_internal_secret)
    token, tools, level = await _resolve_agent(body.user_email, body.agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)

    run_id = await agent_activity.start_run(
        body.agent_id, body.user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=body.agent_id, messages=body.messages,
            tool_ids=tools or None, user_email=body.user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
        outcome = "completed"
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(body.user_email, body.agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)
