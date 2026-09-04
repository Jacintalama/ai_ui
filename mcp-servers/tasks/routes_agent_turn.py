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
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import agent_access
import agent_activity
import agent_routing
from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                          CHANNEL_MAX_TOOL_ITERATIONS,
                          CHAT_TOKEN_TTL_SECONDS, _chat, _list_agents,
                          _owui_user_id_for, _post_chat)
from agent_tools import execute_tool_call
from db import session
from models import BotState
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


async def _run_turn(user_email: str, agent_id: str,
                    messages: list[dict]) -> dict:
    """Run one turn as this user's agent, tools and all.

    Split out of the endpoint so /agents/chat can reuse it without going back
    out over HTTP to ourselves. Returns the same two shapes the endpoint does.
    """
    token, tools, level = await _resolve_agent(user_email, agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)

    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=messages,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
        outcome = "completed"
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)


@router.post("/turn")
async def turn(body: TurnIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Run one turn as this user's agent, tools and all."""
    _require_internal(x_internal_secret)
    return await _run_turn(body.user_email, body.agent_id, body.messages)


#: Fed back as the tool result when the owner said no, so the agent can say
#: what happened in its own words instead of going quiet.
REFUSED_BY_OWNER = "Refused: the owner did not approve this action"

#: Levels that may still act when a held turn is picked back up. `ask` is
#: here because that is the level the question was asked under; `all` because
#: an agent moved up in the meantime is more permitted, not less.
_RESUMABLE = frozenset({agent_access.MODE_ASK, agent_access.MODE_FULL})


@router.post("/turn/resume")
async def resume(body: ResumeIn,
                 x_internal_secret: str = Header(default="")) -> dict:
    """Continue a turn that stopped to ask.

    The access level is READ AGAIN here rather than trusted from when the
    question was asked. Between the two there is a window in which the agent
    can be edited or deleted, and somebody who has second thoughts and turns
    an agent down to read only has turned it down.
    """
    _require_internal(x_internal_secret)
    token, tools, level = await _resolve_agent(body.user_email, body.agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)
    if mode not in _RESUMABLE:
        return {"answer": "This agent is set to read only now, so I did not "
                          "run that.", "notes": []}

    convo = list(body.conversation)
    for call in body.calls:
        call = call if isinstance(call, dict) else {}
        fn = call.get("function")
        fn = fn if isinstance(fn, dict) else {}
        raw_name = fn.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if body.approved:
            # tools, not anything the caller sent: same rule as the turn
            # endpoint, and the reason execute_tool_call takes this argument.
            result = await execute_tool_call(call, body.user_email,
                                             tools or None)
        else:
            result = (REFUSED_BY_OWNER + ", so " + (name or "that tool")
                      + " was not run.")
        # Every tool_call in the held assistant message needs a matching tool
        # message before the next completion, approved or not.
        convo.append({"role": "tool", "tool_call_id": call.get("id"),
                      "name": name, "content": result})

    run_id = await agent_activity.start_run(
        body.agent_id, body.user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=body.agent_id, messages=convo,
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


#: A woken agent stays awake for a week of chatting unless released. Long
#: because a pin is a preference, not a lock. Five minutes of quiet, refreshed
#: on every reply the agent gives: long enough that a person reading and
#: typing a follow up never loses their agent, short enough that walking
#: away and coming back does not hand a new topic to an agent nobody named.
#: Ralph asked for exactly this on 2026-09-04, after a pinned agent kept
#: answering a conversation it was no longer part of.
PIN_TTL_SECONDS = 60 * 5


class ChatIn(BaseModel):
    user_email: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    messages: list[dict]
    #: A caller that has its own way of answering when no agent is involved
    #: sets this, and gets an empty turn list back instead of IO's answer.
    #: The Auto (Free) pipe needs it: IO answers for itself THROUGH that
    #: pipe, so without this flag Auto asking here would recurse into
    #: itself. With it, Auto asks "is anyone named or awake", renders them
    #: if so, and otherwise carries on to its free model as before.
    route_only: bool = False


def _pin_key(chat_id: str, user_email: str) -> str:
    """state_key is the primary key, so the pin must be scoped per PERSON,
    not just per chat_id. Two real values collapse chat_id across everybody
    on the box: the pipe's own "web" default for a caller with no chat
    metadata, and "local", which open-webui-functions/langfuse_filter.py
    already special-cases for temporary chats. Without the email, one
    person naming an agent in a temporary chat would answer a different
    person's temporary chat with it, and one person's stale-pin cleanup
    would delete another person's live pin.
    """
    return "agentpin:web:%s:%s" % (user_email, chat_id)


async def _read_pin(key: str) -> str | None:
    """The pinned agent id for this chat, or None. Never raises.

    Fails open the way the channel pin does: a state outage must not stop
    somebody chatting, and the cost of a missed pin is that they say the name
    again.
    """
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
            return None
        value = row.value
        return value.get("agent_id") if isinstance(value, dict) else None
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read the agent pin", exc_info=True)
        return None


async def _write_pin(key: str, agent_id: str) -> None:
    """Remember which agent is awake. Never raises."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=PIN_TTL_SECONDS)
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
            if row:
                row.value = {"agent_id": agent_id}
                row.updated_at = datetime.now(timezone.utc)
                row.expires_at = expires
            else:
                s.add(BotState(state_key=key, value={"agent_id": agent_id},
                               updated_at=datetime.now(timezone.utc),
                               expires_at=expires))
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not write the agent pin", exc_info=True)


async def _clear_pin(key: str) -> None:
    """Send the agent back to sleep. Never raises."""
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
            if row:
                await s.delete(row)
                await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not clear the agent pin", exc_info=True)


#: _list_agents returns every workspace model this person owns, agents and
#: plain derived models alike. Every other consumer of that same listing
#: filters on this prefix (webhook-handler/gateway/agent_router.py,
#: static/cron.html), and this one must too, for two reasons: a non-agent
#: model getting matched and woken as though it were an agent, and this
#: branch's own pipe registering a model whose id is "io" - unfiltered, a
#: message that merely mentions "socket.io" could match it and _chat(model=
#: "io") would re-enter the pipe and recurse until timeout.
AGENT_PREFIX = "agent-"


async def _agents_for(user_email: str) -> list[dict]:
    """This person's own agents, or an empty list.

    Empty on ANY doubt, including a listing that was cut short: matching a
    name against a partial list could wake a different agent whose name
    happens to be similar, and waking the wrong agent is worse than waking
    none.
    """
    try:
        owner = await _owui_user_id_for(user_email)
        if not owner:
            return []
        token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)
        agents, truncated = await _list_agents(token)
        if truncated:
            return []
        return [a for a in agents if isinstance(a, dict)
                and isinstance(a.get("id"), str)
                and a["id"].startswith(AGENT_PREFIX)]
    except Exception:                                       # noqa: BLE001
        logger.warning("could not list agents for routing", exc_info=True)
        return []


#: What IO answers with when no agent was named. Read from the environment so
#: it can be changed without editing this file, and defaulting to the model the
#: channel gateway already uses so the assistant sounds the same in both places.
#: Must stay "auto_router.auto" to match webhook-handler/config.py's default
#: and the compose fallback for this service's own GATEWAY_MODEL var:
#: "gpt-4o-mini" is not a model id on this platform, so that fallback firing
#: would fail every base-model turn.
IO_BASE_MODEL = os.environ.get("GATEWAY_MODEL", "auto_router.auto")

IO_DOWN = ("I could not reach the model just now. Try again in a moment.")

#: Said when somebody releases the agent they were talking to. A fixed
#: sentence rather than a model call: they asked for something specific and
#: cheap, and spending a completion to say "ok" is waste.
RELEASED = "Back to normal. I will answer from here."

#: Shown when a turn's answer came back empty.
EMPTY_TURN = "There was nothing to answer."


def render_turns(turns) -> str:
    """The reply as a person reads it: each agent's answer under its name,
    a blank line between agents, a turn with no agent shown bare.

    One renderer, here, because two pipes now show these turns and the
    page splits a reply back into per-agent messages by exactly this
    shape: a line that is the agent's name and a colon, then the answer.
    A second copy of this in a pipe would drift from the page's parser.
    """
    parts = []
    for turn in turns if isinstance(turns, list) else []:
        if not isinstance(turn, dict):
            continue
        agent = turn.get("agent")
        agent = agent if isinstance(agent, dict) else None
        answer = (turn.get("answer") or "").strip()
        notes = [n for n in (turn.get("notes") or []) if isinstance(n, str)]
        if notes:
            joined = "\n".join(notes)
            answer = (answer + "\n\n" + joined) if answer else joined
        answer = answer or EMPTY_TURN
        if agent is None:
            parts.append(answer)
        else:
            name = agent.get("name") or agent.get("id") or "Agent"
            parts.append("%s:\n%s" % (name, answer))
    return "\n\n".join(parts)


async def _answer_as_io(user_email: str, messages: list[dict]) -> str:
    """IO speaking for itself, on the base model, as this user.

    Uses the same per-user minted token every agent turn uses, so the answer
    is attributed to the right person and their own model access applies.
    """
    owner = await _owui_user_id_for(user_email)
    if not owner:
        return IO_DOWN
    token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)
    data = await _post_chat(
        {"model": IO_BASE_MODEL, "messages": messages, "stream": False},
        token, CHANNEL_HTTP_TIMEOUT_SECONDS)
    choices = data.get("choices") or []
    if not choices:
        return IO_DOWN
    return ((choices[0].get("message") or {}).get("content") or "").strip() or IO_DOWN


#: Said in place of an answer when a named agent's own turn blew up. One
#: agent failing must not cost the others theirs: Ada's answer must not be
#: lost because Mia's tool timed out.
def _turn_failed_sentence(name: str) -> str:
    return "%s could not answer just now. Try again in a moment." % (name or "That agent")


async def _turn_for(user_email: str, agent: dict, messages: list[dict],
                    names=()) -> dict:
    """One rendered turn for a single named agent. Never raises.

    Wraps _run_turn so a blown-up tool call in one agent's turn cannot take
    the rest of the message down with it.

    `names` is every agent name this person has. The rendered history
    carries "Ada:" and "Mia:" lines so a person can see who spoke, and fed
    back verbatim those lines taught the model the format: it began
    prefixing its own answers with a name and then inventing whole
    exchanges between the agents. So the agent sees history with the labels
    removed, and any label it still echoes at the top of its answer is
    removed before the real one is added.
    """
    history = agent_routing.clean_history_for_agent(messages, names)
    try:
        out = await _run_turn(user_email, agent["id"], history)
    except Exception:                                       # noqa: BLE001
        logger.warning("agent turn failed for %s", agent.get("id"),
                       exc_info=True)
        out = {"answer": _turn_failed_sentence(agent.get("name")), "notes": []}
    out = dict(out)  # Defensive copy: caller must never get a shared dict modified
    out["answer"] = agent_routing.strip_leading_labels(out.get("answer"), names)
    out["agent"] = {"id": agent["id"], "name": agent.get("name") or agent["id"]}
    return out


@router.post("/chat")
async def chat(body: ChatIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Who should answer this message, one turn each.

    Returns {"turns": [...]}. A turn with agent=None is the caller's cue that
    IO answered for itself. Naming more than one agent runs them in spoken
    order, one at a time never in parallel, because each turn can run tools
    and this box has 3.8GB of RAM. The caller holds no routing logic so that
    Discord, Telegram and the web chat all decide this the same way.
    """
    _require_internal(x_internal_secret)
    key = _pin_key(body.chat_id, body.user_email)
    text = agent_routing.last_user_text(body.messages)

    if agent_routing.wants_release(text):
        await _clear_pin(key)
        turns = [{"agent": None, "answer": RELEASED, "notes": []}]
        return {"turns": turns, "rendered": render_turns(turns)}

    agents = await _agents_for(body.user_email)
    named = agent_routing.match_agents(text, agents)

    if named:
        # Naming agents switches rather than stacking: the LAST one named is
        # who a follow up with no name goes to, so "actually ada, you take
        # this" hands over cleanly even when Mia was also named.
        names = [a.get("name") for a in agents if a.get("name")]
        turns = []
        for agent in named:
            turns.append(await _turn_for(body.user_email, agent, body.messages, names))
        await _write_pin(key, named[-1]["id"])
        return {"turns": turns, "rendered": render_turns(turns)}

    pinned_id = await _read_pin(key)
    agent = next((a for a in agents if a.get("id") == pinned_id), None)
    if pinned_id and agent is None:
        # Deleted, or renamed out from under the pin. Fail closed to no
        # agent rather than erroring on every message from here on. Falls
        # through to IO below rather than returning here: a stale pin is
        # an accident the person did not cause, so they get a real answer
        # to what they actually typed, not silence.
        await _clear_pin(key)

    if agent is None and getattr(body, "route_only", False):
        # The caller will answer for itself. Saying so with an empty list
        # rather than an IO answer is what keeps the Auto pipe from asking
        # IO, which would ask Auto, which would ask here again.
        return {"turns": [], "rendered": ""}

    if agent is None:
        # IO speaking for itself. Done here rather than in the pipe because
        # the pipe holds no Open WebUI credentials, and this service already
        # mints a per-user token for every agent turn.
        try:
            answer = await _answer_as_io(body.user_email, body.messages)
        except Exception:                                   # noqa: BLE001
            logger.warning("the base model did not answer", exc_info=True)
            answer = IO_DOWN
        turns = [{"agent": None, "answer": answer, "notes": []}]
        return {"turns": turns, "rendered": render_turns(turns)}

    # A follow up keeps the agent awake. Without this the pin would run out
    # five minutes after the agent was last NAMED, mid conversation.
    names = [a.get("name") for a in agents if a.get("name")]
    turn = await _turn_for(body.user_email, agent, body.messages, names)
    await _write_pin(key, agent["id"])
    return {"turns": [turn], "rendered": render_turns([turn])}
