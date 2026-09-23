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
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import agent_access
import agent_activity
import agent_brief
import agent_escalation
import agent_graph
import agent_memory
import agent_routing
import routes_prefs
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
#: as its own status so the card does not claim the agent is working until
#: agent_activity's stale window calls the run dead, waiting for a reply that
#: may never come.
STATUS_WAITING = "waiting"

#: The shape of an agent id this service mints, and the only shape the
#: turn marker will carry. See turns_marker.
_MARKER_ID_RE = re.compile(r"agent-[A-Za-z0-9_-]+")


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


#: An agent must not reach the tool that runs agents. It is already inside a
#: turn, so calling it would start a round inside a round, and the person is
#: waiting on the outer one.
_TOOLS_AN_AGENT_MAY_NOT_HAVE = frozenset({"agents"})

#: An agent limited to the tools somebody actually picked. Anything else,
#: including absent and including junk, means everything the owner can reach,
#: which is what every agent has always done.
TOOL_SCOPE_PICKED = agent_brief.TOOL_SCOPE_PICKED


async def _every_tool_for(user_email: str) -> list[str]:
    """Every tool this person can use, whatever any one agent was ticked for.

    An agent that cannot answer "which apps have I connected" guesses, and a
    guess about somebody's own account reads as a lie. The access level still
    decides what it may DO with any of them: this widens what it can reach,
    not what it may change without asking.

    Imported inside the function because routes_agents imports this module,
    and at module level that is a cycle.
    """
    try:
        from routes_agents import tools_for_email
        listed = await tools_for_email(user_email)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not list this person's tools", exc_info=True)
        return []
    items = listed.get("tools") if isinstance(listed, dict) else listed
    out = []
    for item in items if isinstance(items, list) else []:
        tool_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(tool_id, str) and tool_id not in _TOOLS_AN_AGENT_MAY_NOT_HAVE:
            out.append(tool_id)
    return out


#: Model ids that are pipes which call BACK into this service. An agent whose
#: base model is one of these cannot run at all.
#:
#: It loops: the pipe asks /agents/chat who should answer, that matches the
#: agent, and the agent runs again. The pipe's own route_only guard does not
#: help, because it only short-circuits when NO agent matches, and an agent
#: running itself always matches. Measured 2026-09-10: two agents on Auto
#: (Free) opened dozens of chats a second and restarted Open WebUI twice.
#:
#: Independently, neither pipe forwards `tools`, so an agent on one silently
#: loses every tool and skill it has. Either reason alone would be enough.
#:
#: To regenerate this list:
#:   select id from public.function
#:    where type='pipe' and content like '%/agents/chat%';
#: then map each pipe to its model id: pipe "io" registers model "io.io".
CALLBACK_MODEL_IDS = frozenset({"auto_router.auto", "io.io"})

#: Said in place of an answer, and recognised in routes_agent_chat so it draws
#: as a failure carrying the fix rather than as something the agent said.
AGENT_ON_CALLBACK_MODEL = (
    "This agent is set to a model that cannot run an agent.")


async def _resolve_agent_row(user_email: str, agent_id: str
                             ) -> tuple[str, list[str], str | None, dict, list[dict]]:
    """(token, tool ids, access level, the agent row, every agent listed).

    Raises HTTPException rather than returning a sentinel: every caller here
    would have to re-raise anyway, and a sentinel that got ignored once would
    run a turn with no tools and look like a model problem.

    The row is returned as well as read because the tool loop needs it. A
    free-model agent's fallback pool and its no-reasoning payload are both
    decided from base_model_id and params, and this function was already the
    only place on the chat path that had them.

    The whole listing comes back for the same reason: the brief names the
    other assistants and their jobs, and this call has already paid for that
    list. A caller that fetched it again would page Open WebUI's model list
    twice for one Discord message, on a box where a turn already waits on
    that service's connection pool.
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
    # Before anything is spent on the turn. Running it would not merely fail,
    # it would recurse until something upstream fell over.
    base = agent.get("base_model_id")
    if isinstance(base, str) and base in CALLBACK_MODEL_IDS:
        raise HTTPException(status_code=409,
                            detail=AGENT_ON_CALLBACK_MODEL)
    meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
    return (token, await tools_for_agent(user_email, meta),
            agent_access.level_of(meta), agent, agents)


async def _resolve_agent(user_email: str, agent_id: str) -> tuple[str, list[str], str | None]:
    """The three values every older caller reads. See _resolve_agent_row."""
    token, tools, level, _agent, _roster = await _resolve_agent_row(
        user_email, agent_id)
    return token, tools, level


async def tools_for_agent(user_email: str, meta: dict) -> list[str]:
    """Which tools this agent may use, from its own meta.

    Public and shared on purpose. It used to live inline in _resolve_agent,
    which meant it applied on the chat path and nowhere else, and
    agent_runner.run_agent read meta["toolIds"] verbatim instead. Measured
    2026-09-10: the same agent had twelve tools in chat and one on a
    schedule, and that one was the connected-apps umbrella with nothing
    behind it. So a scheduled agent could read nothing, wrote its report
    from nothing, and its card still said it could use every tool the owner
    had. Nothing in either file said the two surfaces disagreed.

    A schedule may still narrow what its agent may DO, through tool_mode and
    agent_access. That is a separate axis and deliberately still separate:
    what it may reach should not depend on which surface woke it.
    """
    own = meta.get("toolIds")
    own = [t for t in own if isinstance(t, str)] if isinstance(own, list) else []
    own = [t for t in own if t not in _TOOLS_AN_AGENT_MAY_NOT_HAVE]

    # Narrowed on purpose, and only then. Everything else, including anything
    # unrecognised, means the behaviour this has always had: an agent that
    # cannot look up its owner's own account guesses, and a guess about
    # somebody's own things reads as a lie.
    #
    # Picking nothing is not a request for nothing. Somebody who chose the
    # narrow option and then unticked every box has not finished choosing,
    # and an agent with no tools at all would simply look broken.
    if meta.get("toolScope") == TOOL_SCOPE_PICKED and own:
        return own

    # Everything this person can reach, not only what this agent was ticked
    # for. Its own list stays in front so an explicitly granted tool is never
    # lost if the wider read comes back short.
    tools = list(own)
    for tool_id in await _every_tool_for(user_email):
        if tool_id not in tools:
            tools.append(tool_id)
    return tools


def _last_user_text(messages: list[dict]) -> str:
    """What the person actually typed this turn, for the reflection.

    The last user message rather than the first or the whole list: by the
    time a turn reaches here the messages carry the identity line, the
    recall block and the earlier turns of the conversation, and reflecting
    on all of that would write down again what was settled days ago.
    """
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            return content if isinstance(content, str) else ""
    return ""


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


async def _run_turn(user_email: str, agent_id: str, messages: list[dict],
                    brief: bool = False) -> dict:
    """Run one turn as this user's agent, tools and all.

    Split out of the endpoint so /agents/chat can reuse it without going back
    out over HTTP to ourselves. Returns the same two shapes the endpoint does.

    `brief` is for callers that have not built one. _turn_for builds its own
    and passes it in front of the history, because it runs several agents
    over one message and reads the account once for all of them. The bot
    gateway has no such round, and the row and roster a brief needs are
    resolved here anyway, so asking for it here is what stops that endpoint
    fetching the same listing a second time.
    """
    token, tools, level, agent, roster = await _resolve_agent_row(
        user_email, agent_id)
    if brief:
        made = await _brief_for(user_email, agent, roster, messages)
        messages = [made] + messages
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)

    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    # Who is asking. The room says so through agent_escalation.asking,
    # because only it can tell the person's words from its own PASS
    # instruction; every other chat surface hands this the person's own
    # messages, so the last user message is what they typed.
    intent = (agent_escalation.current_intent()
              or agent_escalation.Intent(person_text=_last_user_text(messages)))
    usage = agent_escalation.TurnUsage(run_id=run_id)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=messages,
            agent=agent,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS,
            intent=intent, usage=usage)
        outcome = "completed"
        if not answer and notes:
            # The loop writes a note when it stops at the iteration cap or
            # refuses a write, and this path used to throw it away and return
            # an empty string. An empty bubble tells the person nothing and
            # reads as the agent ignoring them; the note says what happened.
            # The schedule path has always done this; the chat path did not,
            # which only surfaced once agents used enough rounds to hit the
            # cap by looking a skill up first.
            answer = "\n".join(notes)
            notes = []
        # The subconscious: after a real answer, one detached completion
        # writes down what was settled. Fire and forget, never awaited here.
        agent_memory.schedule_reflection(
            user_email, agent, token, _last_user_text(messages), answer)
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome, usage=usage)


@router.post("/turn")
async def turn(body: TurnIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Run one turn as this user's agent, tools and all."""
    _require_internal(x_internal_secret)
    # Discord, Slack and Telegram arrive here, not through _turn_for, so the
    # brief has to be built on this path too. It used to be the recall block
    # alone, on the grounds that this endpoint has neither the agent row nor
    # the other agents' names: _run_turn resolves both to run the turn at
    # all, so asking it for a brief costs nothing, and doing without one left
    # every bot turn with no skills, no account context and no idea what its
    # own job was.
    return await _run_turn(body.user_email, body.agent_id,
                           list(body.messages), brief=True)


#: Fed back as the tool result when the owner said no, so the agent can say
#: what happened in its own words instead of going quiet.
REFUSED_BY_OWNER = "Refused: the owner did not approve this action"

#: Levels that may still act when a held turn is picked back up. `ask` is
#: here because that is the level the question was asked under; `all` because
#: an agent moved up in the meantime is more permitted, not less.
_RESUMABLE = frozenset({agent_access.MODE_ASK, agent_access.MODE_FULL})


async def _resume_turn(user_email: str, agent_id: str, conversation: list[dict],
                       calls: list[dict], approved: bool) -> dict:
    """Continue a turn that stopped to ask.

    Split out of the route so callers inside this process (the agent chat
    panel) can resume without an HTTP hop and without holding the internal
    secret, the same way the Fusion page calls fusion_engine directly.

    The access level is READ AGAIN here rather than trusted from when the
    question was asked. Between the two there is a window in which the agent
    can be edited or deleted, and somebody who has second thoughts and turns
    an agent down to read only has turned it down.
    """
    token, tools, level, agent, _roster = await _resolve_agent_row(
        user_email, agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)
    if mode not in _RESUMABLE:
        return {"answer": "This agent is set to read only now, so I did not "
                          "run that.", "notes": []}

    convo = list(conversation)
    for call in calls:
        call = call if isinstance(call, dict) else {}
        fn = call.get("function")
        fn = fn if isinstance(fn, dict) else {}
        raw_name = fn.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if approved:
            # tools, not anything the caller sent: same rule as the turn
            # endpoint, and the reason execute_tool_call takes this argument.
            # agent_id goes with it so a tool that acts as the agent still
            # knows which agent this is on the resumed half of the turn.
            result = await execute_tool_call(call, user_email, tools or None,
                                             agent_id)
        else:
            result = (REFUSED_BY_OWNER + ", so " + (name or "that tool")
                      + " was not run.")
        # Every tool_call in the held assistant message needs a matching tool
        # message before the next completion, approved or not.
        convo.append({"role": "tool", "tool_call_id": call.get("id"),
                      "name": name, "content": result})

    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    # An approval is the same job carrying on, so it stays on whichever
    # model this agent was on for this person, for as long as that lasts.
    usage = agent_escalation.TurnUsage(run_id=run_id)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=convo,
            agent=agent,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS,
            intent=agent_escalation.Intent(follow_up=True), usage=usage)
        outcome = "completed"
        if not answer and notes:
            # The loop writes a note when it stops at the iteration cap or
            # refuses a write, and this path used to throw it away and return
            # an empty string. An empty bubble tells the person nothing and
            # reads as the agent ignoring them; the note says what happened.
            # The schedule path has always done this; the chat path did not,
            # which only surfaced once agents used enough rounds to hit the
            # cap by looking a skill up first.
            answer = "\n".join(notes)
            notes = []
        # This path returns straight to the approval handler without passing
        # through _turn_for, and it is where "Done, I added the page" style
        # replies come from, so it scrubs the same way.
        return {"answer": agent_routing.scrub_long_dashes(answer),
                "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome, usage=usage)


@router.post("/turn/resume")
async def resume(body: ResumeIn,
                 x_internal_secret: str = Header(default="")) -> dict:
    """Continue a turn that stopped to ask. Internal only.

    The work is in _resume_turn so in-process callers can reach it without
    holding the internal secret.
    """
    _require_internal(x_internal_secret)
    return await _resume_turn(user_email=body.user_email,
                              agent_id=body.agent_id,
                              conversation=body.conversation,
                              calls=body.calls, approved=body.approved)


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
    #: The web page takes turns: the pipe shows the first agent's reply and
    #: the page fetches each further agent itself, so they arrive one after
    #: another as separate messages. With this set, only the first matched
    #: agent runs here and the rest come back as `queue`. Discord and
    #: Telegram send one message per turn already and never set it.
    first_only: bool = False


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

    The name is bold markdown on its own line rather than "Ada:" in plain
    text. Open WebUI renders one tool reply as exactly one message and
    nothing can change that, so when two agents answer, the only thing left
    to fix is whether that one message READS as two speakers. Flat text did
    not; a bold heading above each answer does.

    Whatever this emits, agent_routing must be able to strip back out: the
    same lines fed to an agent as history taught it to invent whole
    exchanges between agents. See _label_line_re, which matches this shape
    and the older one.
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
            parts.append("**%s**\n\n%s" % (name, answer))
    return "\n\n".join(parts)


def turns_marker(ids) -> str:
    """The hidden line that tells the page who answers and in what order.

    Empty unless at least two agents answer, because a single reply needs
    nothing from the page. Model ids, never names: a name can be renamed
    under a stored message and an id cannot, and the page hands these ids
    straight back to /agents/speak. An HTML comment renders as nothing and
    survives the round trip through the chat's own storage, which is what
    lets the page find it again after a reload.
    """
    # Only ids of the shape this service mints. A model id in Open WebUI is
    # free text set by whoever created the model, and this string lands
    # inside an HTML comment: "-->" in an id would end the comment early
    # and put the rest into the page as markup, and a comma would mis-split
    # on the page's parse. Refusing the id is safer than escaping it, since
    # a refused agent still answered; it just does not get a turn here.
    ids = [i for i in (ids if isinstance(ids, list) else [])
           if isinstance(i, str) and _MARKER_ID_RE.fullmatch(i)]
    if len(ids) < 2:
        return ""
    return "<!-- aiui:turns %s -->" % ",".join(ids)


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


#: The brief lives in agent_brief so every surface can build the same one.
#: Kept as a name here because this module's own callers, and the tests that
#: pin what the brief says, have always reached it through this one.
_identity_line = agent_brief.build


async def clock_for(user_email: str) -> datetime:
    """The time on this person's own clock, for a brief.

    Public because a caller running several agents over one message reads it
    once and passes it to each of them. read_timezone opens a connection per
    call, and the clock does not move between two agents answering the same
    question.
    """
    try:
        tz, _source = await routes_prefs.read_timezone(user_email)
    except Exception:                                       # noqa: BLE001
        # read_timezone says it never raises. If that stops being true, the
        # turn loses the right clock, not the answer.
        logger.warning("could not read the timezone for %s", user_email,
                       exc_info=True)
        tz = ""
    return agent_brief.now_in(tz or "")


async def _brief_for(user_email: str, agent: dict, roster: list[dict],
                     messages: list[dict]) -> dict:
    """The brief for a turn nobody else built one for.

    Every part of it is optional and every part fails open on its own, which
    is the whole reason this is not one try block: a bot turn answering
    without its skills is worse than one with them and far better than none.
    The identity, the role and the tools sentence come off the row this was
    handed, so those are there whatever else fails.
    """
    agent_id = agent.get("id")
    try:
        memory = await agent_memory.recall_block(user_email, agent_id)
    except Exception:                                       # noqa: BLE001
        # recall_block already fails open, so this only catches a bug in it,
        # and a bug there must cost the memory, not the bot's answer.
        logger.warning("could not read agent memory for %s", agent_id,
                       exc_info=True)
        memory = ""
    names = [a.get("name") for a in roster
             if isinstance(a, dict) and a.get("name")]
    graph = await agent_graph.graph_block(
        user_email, agent_routing.last_user_text(messages))
    return agent_brief.build(agent, names, memory=memory, roster=roster,
                             graph=graph, now=await clock_for(user_email))


async def _turn_for(user_email: str, agent: dict, messages: list[dict],
                    names=(), roster=(), graph: str = "",
                    now: datetime | None = None) -> dict:
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
    try:
        memory = await agent_memory.recall_block(user_email, agent["id"])
    except Exception:                                       # noqa: BLE001
        # Its own arm, not the one below. Sharing that one would answer a
        # broken memory read with the sentence that says the turn failed,
        # spending the whole answer on the one part of it that is optional.
        logger.warning("could not read agent memory for %s", agent.get("id"),
                       exc_info=True)
        memory = ""
    # A caller running a round reads this once and hands the same clock to
    # everybody, the way it does with the graph block: read_timezone opens
    # its own Postgres connection and closes it, so a per-agent read would
    # cost a connection per agent per message. Only a caller running one
    # agent leaves it out, and then this is the one read.
    if now is None:
        now = await clock_for(user_email)
    try:
        history = ([_identity_line(agent, names, memory=memory,
                                   roster=roster, graph=graph, now=now)]
                   + agent_routing.clean_history_for_agent(messages, names))
        out = await _run_turn(user_email, agent["id"], history)
    except Exception as exc:                                # noqa: BLE001
        # One failure is worth naming rather than generalising: an agent on a
        # callback pipe cannot run at all, and the person fixes it in one
        # click. It is also not a surprise, so it is not logged as one.
        if getattr(exc, "detail", None) == AGENT_ON_CALLBACK_MODEL:
            out = {"answer": AGENT_ON_CALLBACK_MODEL, "notes": []}
        else:
            logger.warning("agent turn failed for %s", agent.get("id"),
                           exc_info=True)
            out = {"answer": _turn_failed_sentence(agent.get("name")),
                   "notes": []}
    out = dict(out)  # Defensive copy: caller must never get a shared dict modified
    # Scrubbed, not requested: the brief forbids long dashes and the model
    # used one in 25 of 36 replies anyway.
    out["answer"] = agent_routing.scrub_long_dashes(
        agent_routing.strip_leading_labels(out.get("answer"), names))
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
        return {"turns": turns, "rendered": render_turns(turns), "queue": [], "marker": ""}

    agents = await _agents_for(body.user_email)
    named = agent_routing.match_agents(text, agents)

    if named:
        # Naming agents switches rather than stacking: the LAST one named is
        # who a follow up with no name goes to, so "actually ada, you take
        # this" hands over cleanly even when Mia was also named.
        names = [a.get("name") for a in agents if a.get("name")]
        # Once for the message, not once per agent: naming two agents runs two
        # turns about one question, and the account has not changed between
        # them.
        graph = await agent_graph.graph_block(body.user_email, text)
        now = await clock_for(body.user_email)
        speakers = named[:1] if getattr(body, "first_only", False) else named
        turns = []
        for agent in speakers:
            turns.append(await _turn_for(body.user_email, agent, body.messages,
                                         names, roster=agents, graph=graph,
                                         now=now))
        # An approval interrupts the round for the agent that asked: the
        # pin goes to the one who is waiting, not to the last one named,
        # so the person's yes or no reaches them.
        #
        # Everybody else still speaks. Withholding the marker here as
        # well used to drop every other addressed agent for good: "hi
        # team, delete the stale rows" with Ada on Ask had Ada ask, and
        # Mia never spoke and was never mentioned. Pausing Ada is the
        # point; silently losing Mia was not.
        first_pending = bool(turns) and isinstance(turns[0].get("pending"), dict) \
            and bool(turns[0]["pending"].get("calls"))
        first_only = bool(getattr(body, "first_only", False))
        queue = [a["id"] for a in named[1:]] if first_only else []
        ids = [a["id"] for a in named] if queue else []
        if first_pending:
            await _write_pin(key, named[0]["id"])
            return {"turns": turns, "rendered": render_turns(turns),
                    "queue": queue, "marker": turns_marker(ids)}
        await _write_pin(key, named[-1]["id"])
        return {"turns": turns, "rendered": render_turns(turns),
                "queue": queue, "marker": turns_marker(ids)}

    pinned_id = await _read_pin(key)
    agent = next((a for a in agents if a.get("id") == pinned_id), None)
    if pinned_id and agent is None:
        # Deleted, or renamed out from under the pin. Fail closed to no
        # agent rather than erroring on every message from here on. Falls
        # through to IO below rather than returning here: a stale pin is
        # an accident the person did not cause, so they get a real answer
        # to what they actually typed, not silence.
        await _clear_pin(key)

    if agent is None:
        # Nobody named and nobody pinned. Before handing this to IO, the same
        # ladder the panel uses gets a look: if exactly one agent owns the
        # subject, "anything unread in my inbox" is a question for the one
        # agent with the mailbox, not a question for a general model that
        # cannot see it. Only when it is unambiguous, so a room where two
        # agents read email still falls through.
        owner = agent_routing.domain_owner(text, agents)
        if owner is not None:
            agent = owner

    if agent is None and getattr(body, "route_only", False):
        # The caller will answer for itself. Saying so with an empty list
        # rather than an IO answer is what keeps the Auto pipe from asking
        # IO, which would ask Auto, which would ask here again.
        return {"turns": [], "rendered": "", "queue": [], "marker": ""}

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
        return {"turns": turns, "rendered": render_turns(turns), "queue": [], "marker": ""}

    # A follow up keeps the agent awake. Without this the pin would run out
    # five minutes after the agent was last NAMED, mid conversation.
    names = [a.get("name") for a in agents if a.get("name")]
    turn = await _turn_for(body.user_email, agent, body.messages, names,
                           roster=agents,
                           graph=await agent_graph.graph_block(
                               body.user_email, text))
    await _write_pin(key, agent["id"])
    return {"turns": [turn], "rendered": render_turns([turn]), "queue": [], "marker": ""}
