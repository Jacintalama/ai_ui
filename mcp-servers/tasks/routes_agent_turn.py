import asyncio
import contextvars
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
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

import agent_access
import agent_approvals
import agent_avatar
import agent_activity
import agent_brief
import agent_decider
import agent_escalation
import agent_graph
import agent_handoff
import agent_jev
import agent_llm
import agent_memory
import agent_progress
import agent_routing
import main_assistant
import agent_skills
import routes_prefs
from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                          CHANNEL_MAX_TOOL_ITERATIONS,
                          CHAT_TOKEN_TTL_SECONDS, FREE_POOL_EXHAUSTED,
                          ROUTER_EXHAUSTED, _chat, _list_agents,
                          _owui_user_id_for, _post_chat)
from agent_tools import execute_tool_call
from db import session
from models import BotState
from owui_token import mint_owui_token, session_stamp_for
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

#: A colleague's turn is shorter than a top-level one because somebody is
#: waiting mid-sentence for it, and agents run one at a time on this box.
COLLEAGUE_HTTP_TIMEOUT_SECONDS = max(30, CHANNEL_HTTP_TIMEOUT_SECONDS // 2)
COLLEAGUE_MAX_TOOL_ITERATIONS = max(1, CHANNEL_MAX_TOOL_ITERATIONS // 2)


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
#: The agents already listed for the message being answered, set by
#: _turn_for around its turn so _resolve_agent_row reads them instead of
#: paging Open WebUI's model list a second time. A context variable rather
#: than a parameter: _run_turn is stood in for by tests and callers with
#: its own signature, and the listing is a fact about the request, not
#: about the turn.
_listing_for_turn: contextvars.ContextVar = contextvars.ContextVar(
    "agents_listed_for_this_message", default=None)

_TOOLS_AN_AGENT_MAY_NOT_HAVE = frozenset({"agents"})
#: The same tool by its title, because an admin names the id when pasting
#: it in: on the live box it is not "agents", and Mia asked to run
#: ask_agents on "hi team" (2026-10-28). agent_tools refuses the method by
#: name as well, whatever the row is called.
_TOOL_TITLES_AN_AGENT_MAY_NOT_HAVE = frozenset({"ask your agents"})

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
        title = str(item.get("label") or "").strip().lower() if isinstance(item, dict) else ""
        if (isinstance(tool_id, str) and tool_id not in _TOOLS_AN_AGENT_MAY_NOT_HAVE
                and title not in _TOOL_TITLES_AN_AGENT_MAY_NOT_HAVE):
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
#: Kept in agent_llm since 2026-10-27, when an agent on a pipe became
#: able to run through meta.llm; this name stays for its readers.
CALLBACK_MODEL_IDS = agent_llm.CALLBACK_IDS

#: Said in place of an answer, and recognised in routes_agent_chat so it draws
#: as a failure carrying the fix rather than as something the agent said.
AGENT_ON_CALLBACK_MODEL = (
    "This agent is set to a model that cannot run an agent.")

#: Said when a message arrives for an agent id that is not one of this
#: person's agents: deleted since the chat was opened, or somebody else's.
NOT_YOUR_AGENT = ("That agent is not one of yours any more. Pick another "
                  "model, or make the agent again on the Agents page.")


async def _resolve_agent_row(user_email: str, agent_id: str,
                             listing: list[dict] | None = None
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
    token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS,
                            session_stamp=await session_stamp_for(owner))
    # `listing` is the agents the caller already fetched for this message
    # (/agents/chat lists them to route), so one message does not page Open
    # WebUI's model list twice. A caller with none, or one that may be
    # short, leaves it None and the list is read here as it always was.
    listing = listing or _listing_for_turn.get()
    if listing:
        agents, truncated = list(listing), False
    else:
        agents, truncated = await _list_agents(token)
    if main_assistant.is_assistant(agent_id):
        # The main chat's own assistant is not a row in Open WebUI. It may
        # reach everything this person can, and asks before it changes
        # anything; a turn narrows the tools to what Jev picked.
        return (token, await _every_tool_for(user_email),
                agent_access.MODE_ASK, main_assistant.agent(), agents)
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
    # Since 2026-10-27 an agent on a pipe runs when meta.llm names its
    # model (agent_llm): the runner posts that model, never the pipe. One
    # on a pipe with no model is the old loop, and is still refused here.
    if (agent_llm.is_callback(agent.get("base_model_id"))
            and not agent_llm.can_run(agent)):
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

    # A "picked" scope is no longer a limit (2026-10-28). Nobody ticks tools
    # now: each message carries what Jev picked for it (_auto_tools), and
    # a hand-ticked list saved before then would quietly keep an agent from
    # tools nobody can see it lacks any more.

    # Everything this person can reach, not only what this agent was ticked
    # for. Its own list stays in front so an explicitly granted tool is never
    # lost if the wider read comes back short.
    tools = list(own)
    for tool_id in await _every_tool_for(user_email):
        if tool_id not in tools:
            tools.append(tool_id)
    return tools


#: Kept on every agent turn whatever Jev picks: looking up its own skills,
#: saving a note, asking a colleague. A pick of "none" for "run the weekly
#: review" would otherwise leave an agent unable to read its own procedure.
AGENT_CORE_TOOLS = frozenset({"skills", "remember", "colleague"})

#: One pick per message. A room round runs every agent over the same words,
#: and each asking Jev again would pay for the same answer once per agent.
PICK_TTL_SECONDS = 120.0
_PICKS: dict[tuple, tuple[float, list[str] | None]] = {}


async def _auto_tools(user_email: str, text: str,
                      tools: list[str]) -> list[str]:
    """The tools an agent gets for this message: what Jev is sure it needs,
    plus AGENT_CORE_TOOLS, in the order given. Every tool when Jev could
    not be asked, so an agent never does worse than before there was a pick.
    Never raises."""
    text = (text or "").strip()
    if not tools or not text:
        return list(tools)
    key = (user_email, text, tuple(tools))
    now = time.monotonic()
    hit = _PICKS.get(key)
    if hit is not None and now - hit[0] < PICK_TTL_SECONDS:
        picked = hit[1]
    else:
        try:
            picked = await agent_jev.pick_tools(user_email, text, tools)
        except Exception:                                   # noqa: BLE001
            logger.warning("tool pick failed", exc_info=True)
            picked = None
        for k in [k for k, v in _PICKS.items()
                  if now - v[0] >= PICK_TTL_SECONDS]:
            _PICKS.pop(k, None)
        _PICKS[key] = (now, picked)
    if picked is None:
        return list(tools)
    keep = set(picked) | AGENT_CORE_TOOLS
    return [t for t in tools if t in keep]


def _last_user_text(messages: list[dict]) -> str:
    """What the person actually typed this turn, for the reflection.

    The last user message rather than the first or the whole list: by the
    time a turn reaches here the messages carry the identity line, the
    recall block and the earlier turns of the conversation, and reflecting
    on all of that would write down again what was settled days ago.

    One implementation, in agent_routing, because this had the same blind
    spot the ladder had: a turn with something attached arrives as a list of
    parts, and both read "" from it. The agent would then reflect on nothing
    for every message the person attached a file to.
    """
    return agent_routing.last_user_text(messages or [])


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


def _source_for(surface: str) -> str:
    """What to record as the reason this run exists.

    Pulled out of the start_run call so it can be tested without running a
    turn, which needs a database and a model (the repo's testing-seams
    pattern). The order is the point of it, most specific first:

    Colleague before anything else, because a handoff inside a meeting is
    still a handoff, and "who asked this agent" is the more specific fact.
    A job step next: it is why this run exists, more specifically than the
    meeting it may sit in. Then the meeting. Then the main chat, because a
    meeting called FROM the main chat is still a meeting.

    Channel is last and is a fallback, and that is what hid the main chat:
    its turns were written as "channel", the same value Discord uses, so
    the busiest surface on the platform was the one with no measurements.
    """
    if surface == agent_access.SURFACE_COLLEAGUE:
        return agent_activity.SOURCE_COLLEAGUE
    if surface == agent_access.SURFACE_AUTOMATION:
        return agent_activity.SOURCE_AUTOMATION
    if agent_activity.in_job_step():
        return agent_activity.SOURCE_JOB
    if agent_activity.in_meeting():
        return agent_activity.SOURCE_MEETING
    if agent_activity.in_main_chat():
        return agent_activity.SOURCE_CHAT
    return agent_activity.SOURCE_CHANNEL


async def _run_turn(user_email: str, agent_id: str, messages: list[dict],
                    brief: bool = False,
                    surface: str = agent_access.SURFACE_CHANNEL,
                    parent_run_id: str | None = None,
                    tool_ids: list[str] | None = None) -> dict:
    """Run one turn as this user's agent, tools and all.

    Split out of the endpoint so /agents/chat can reuse it without going back
    out over HTTP to ourselves. Returns the same two shapes the endpoint does.

    `brief` is for callers that have not built one. _turn_for builds its own
    and passes it in front of the history, because it runs several agents
    over one message and reads the account once for all of them. The bot
    gateway has no such round, and the row and roster a brief needs are
    resolved here anyway, so asking for it here is what stops that endpoint
    fetching the same listing a second time.

    `surface` is where this turn is running, which decides what its tools
    may do. A handoff passes SURFACE_COLLEAGUE, which narrows `ask` to read
    only: the owner is in a conversation with the agent that ASKED, so a
    prompt raised here would ask them about a conversation they are not in.

    `parent_run_id` is the run that asked for this one, so the office can
    say who is helping whom as a fact rather than an animation.

    `tool_ids` replaces the resolved tools for this turn: the main chat's
    assistant gets only what Jev picked for the message (main_assistant).
    An empty list is no tools at all; None keeps the resolved list.
    """
    token, tools, level, agent, roster = await _resolve_agent_row(
        user_email, agent_id)
    # Who is asking. The room says so through agent_escalation.asking,
    # because only it can tell the person's words from its own PASS
    # instruction; every other chat surface hands this the person's own
    # messages, so the last user message is what they typed.
    intent = (agent_escalation.current_intent()
              or agent_escalation.Intent(person_text=_last_user_text(messages)))
    if tool_ids is not None:
        tools = list(tool_ids)
    else:
        # Nobody picks an agent's tools: Jev does, per message (2026-10-28).
        # A colleague is picked for the question it was asked, not for the
        # person's words to the agent that asked it.
        tools = await _auto_tools(
            user_email,
            (_last_user_text(messages)
             if surface == agent_access.SURFACE_COLLEAGUE
             else intent.person_text),
            tools)
    if brief:
        made = await _brief_for(user_email, agent, roster, messages)
        messages = [made] + messages
    mode = agent_access.effective_mode(level, None, surface)

    run_id = await agent_activity.start_run(
        agent_id, user_email, _source_for(surface),
        parent_run_id=parent_run_id)
    usage = agent_escalation.TurnUsage(run_id=run_id)
    outcome = "failed"
    # Sets this turn's run on every turn, nested included, and opens the
    # handoff budget only when none is open, so a colleague's turn spends
    # its caller's budget rather than getting a fresh one of its own.
    async with agent_handoff.began(run_id):
        try:
            answer, notes = await _chat(
                token=token, model=agent_id, messages=messages,
                agent=agent,
                tool_ids=tools or None, user_email=user_email,
                tool_mode=mode,
                refusal_reason=agent_access.refusal_reason(
                    level, None, surface),
                max_iterations=(COLLEAGUE_MAX_TOOL_ITERATIONS
                                if surface == agent_access.SURFACE_COLLEAGUE
                                else CHANNEL_MAX_TOOL_ITERATIONS),
                timeout=(COLLEAGUE_HTTP_TIMEOUT_SECONDS
                         if surface == agent_access.SURFACE_COLLEAGUE
                         else CHANNEL_HTTP_TIMEOUT_SECONDS),
                intent=intent, usage=usage)
            outcome = "completed"
            if not answer and notes:
                # The loop writes a note when it stops at the iteration cap or
                # refuses a write, and this path used to throw it away and
                # return an empty string. An empty bubble tells the person
                # nothing and reads as the agent ignoring them; the note says
                # what happened. The schedule path has always done this; the
                # chat path did not, which only surfaced once agents used
                # enough rounds to hit the cap by looking a skill up first.
                answer = "\n".join(notes)
                notes = []
            # The subconscious: after a real answer, one detached completion
            # writes down what was settled. Fire and forget, never awaited
            # here.
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
    # Sets this turn's run on every turn and opens the handoff budget
    # only when none is open. A resumed turn runs a full tool
    # loop of its own (ask_colleague included), so it has to open this
    # itself the same way _run_turn does, or a colleague asked from a
    # resumed turn would get no parent_run_id and spend()/spent() would
    # stay no-ops here, leaving the MAX_PER_TURN arm of refusal() unable
    # to fire on this path.
    async with agent_handoff.began(run_id):
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
    #: The agent this message is for, decided by the caller: the IO pipe
    #: sets it when Open WebUI sent the message to an agent's own model
    #: (@Ada in the main chat, 2026-10-27). That agent answers, whatever
    #: the words say: no name matching, no release, no Jev. An id that is
    #: not one of this person's agents is answered with a sentence saying so.
    agent_id: str | None = None


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


#: How long a question the main chat asked stays answerable. Longer than a
#: pin: somebody may read the question, check something and come back.
PENDING_TTL_SECONDS = 60 * 30


def _pending_key(pin_key: str) -> str:
    """The held call for one chat sits beside its pin, per person too."""
    return pin_key.replace("agentpin:", "agentpending:", 1)


async def _read_pending(key: str) -> dict | None:
    """The call this chat is waiting on a yes or no for, or None. Never
    raises: a state outage costs the person one re-ask, nothing more."""
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
            return None
        return row.value if isinstance(row.value, dict) else None
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read the held approval", exc_info=True)
        return None


async def _write_pending(key: str, pending: dict) -> None:
    """Hold a turn's question until the next message. Never raises."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL_SECONDS)
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
            if row:
                row.value = pending
                row.updated_at = datetime.now(timezone.utc)
                row.expires_at = expires
            else:
                s.add(BotState(state_key=key, value=pending,
                               updated_at=datetime.now(timezone.utc),
                               expires_at=expires))
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not hold the approval", exc_info=True)


async def _clear_pending(key: str) -> None:
    """Forget a held question. Never raises."""
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
            if row:
                await s.delete(row)
                await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not clear the held approval", exc_info=True)


def own_agents(rows: "list | None", owner_id: str) -> list[dict]:
    """The rows of an Open WebUI model listing that are this person's agents.

    Two filters, and both matter.

    The PREFIX is why this function exists at all; see AGENT_PREFIX above.

    The OWNER is the one that was missing. For an admin, /api/v1/models/list
    carries every user's agents whatever their grants, so a name matched
    against that listing could reach somebody else's agent. It always could,
    but it took the admin typing the name; now the name can arrive inside text
    an agent read somewhere, which is exactly the case agent_access's
    docstring says the levels exist to protect against. The colleague still
    runs as the admin's own email, so what leaks is another person's persona
    and its answer rather than their account, and it is worth closing before
    untrusted text can reach it.

    `user_id` is the field because `/api/v1/models/list` is the only listing
    that still carries it on the row, which is why every surface needing
    ownership reads that endpoint: static/agents.html filters
    `m.user_id === state.me` for the same reason and with the same comparison.

    Compared strictly. A row with no `user_id` is a row whose owner we do not
    know, and treating unknown as "yours" is how this hole was dug.
    """
    return [a for a in rows or [] if isinstance(a, dict)
            and isinstance(a.get("id"), str)
            and a["id"].startswith(AGENT_PREFIX)
            and a.get("user_id") == owner_id]


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
        token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS,
                                session_stamp=await session_stamp_for(owner))
        agents, truncated = await _list_agents(token)
        if truncated:
            return []
        return own_agents(agents, owner)
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


#: One argument value in an approval question: enough to recognise a
#: recipient or a subject, not enough for a message body to bury the question.
MAX_ARG_CHARS = 120
MAX_ARGS_SHOWN = 5


def approval_question(agent_name: str, calls) -> str:
    """What the agent wants to do, in its own terms: the tool's name and
    arguments, not a phrase written per tool, which would be wrong somewhere
    and be wrong exactly where somebody approves the wrong thing. The IO
    pipe's wording, here since Auto renders what this service sends."""
    # No name means the assistant asking for itself in the main chat, where
    # the person named nobody. "This agent wants to run" is as wrong there as
    # a robot and a bold IO over the answer: it invents a third party out of
    # the free model's own tool call.
    lines = [("%s wants to run:" % agent_name) if agent_name
             else "This will run:"]
    for call in calls if isinstance(calls, list) else []:
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


def _held(turn) -> bool:
    return (isinstance(turn, dict) and isinstance(turn.get("pending"), dict)
            and bool(turn["pending"].get("calls")))


def render_turns(turns, faces: bool = False) -> str:
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
        if _held(turn):
            answer = approval_question(
                (agent or {}).get("name") or (agent or {}).get("id"),
                turn["pending"]["calls"])
        answer = answer or EMPTY_TURN
        if agent is None:
            parts.append(answer)
        else:
            name = agent.get("name") or agent.get("id") or "Agent"
            # With faces, the office robot stands before the name (the web
            # chat asks for this; Discord and Telegram keep the bold name).
            head = (agent_avatar.reply_face(str(agent.get("id") or ""), name)
                    if faces else "**%s**" % name)
            parts.append("%s\n\n%s" % (head, answer))
    return "\n\n".join(parts)


def _faces_of(turns) -> dict:
    """agent id -> the robot, for every agent that spoke, so a caller that
    renders turns itself (the IO pipe) can show the face too."""
    out = {}
    for turn in turns if isinstance(turns, list) else []:
        agent = turn.get("agent") if isinstance(turn, dict) else None
        if isinstance(agent, dict) and agent.get("id"):
            out[str(agent["id"])] = agent_avatar.data_uri(
                str(agent["id"]), str(agent.get("name") or agent["id"]), agent_avatar.REPLY_SIZE)
    return out


def _reply(turns, queue=None, marker: str = "", status: str = "") -> dict:
    """The /chat response: the turns, two renderings of them (plain, and
    with the agents' faces for the web), the faces by id, and the queue
    and marker the older shape carried.

    `status` is the one line to leave on the person's screen afterwards:
    "Answered by Mia", or "Used your email" when the assistant read
    something, or "" when the free model answered and nothing happened
    worth reporting. Decided here rather than in the pipe because this is
    where it is known whether a real agent spoke or the assistant did, and
    getting that wrong is what put "Answered by your agent" over an answer
    with no agent in it (2026-10-28).
    """
    return {"turns": turns, "rendered": render_turns(turns),
            "rendered_web": render_turns(turns, faces=True),
            "faces": _faces_of(turns), "queue": queue or [], "marker": marker,
            "status": status}


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
    token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS,
                            session_stamp=await session_stamp_for(owner))
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
                    now: datetime | None = None,
                    tool_ids: list[str] | None = None) -> dict:
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
    async def _memory() -> str:
        try:
            return await agent_memory.recall_block(user_email, agent["id"])
        except Exception:                                   # noqa: BLE001
            # Its own arm, not the one below. Sharing that one would answer
            # a broken memory read with the sentence that says the turn
            # failed, spending the whole answer on the one optional part.
            logger.warning("could not read agent memory for %s", agent.get("id"),
                           exc_info=True)
            return ""

    # A caller running a round reads the clock once and hands the same one
    # to everybody, the way it does with the graph block: read_timezone
    # opens its own Postgres connection and closes it, so a per-agent read
    # would cost a connection per agent per message. Only a caller running
    # one agent leaves it out, and then this is the one read. The memory
    # and the clock are two independent reads, so they run side by side
    # (2026-10-28, "smooth and fast"): neither waits for the other.
    if now is None:
        memory, now = await asyncio.gather(_memory(), clock_for(user_email))
    else:
        memory = await _memory()
    try:
        history = ([_identity_line(agent, names, memory=memory,
                                   roster=roster, graph=graph, now=now)]
                   + agent_routing.clean_history_for_agent(messages, names))
        # The roster is this person's own agents, already listed to route
        # the message; handing it on saves the turn a second listing.
        reset = _listing_for_turn.set([a for a in roster if isinstance(a, dict)] or None)
        try:
            out = (await _run_turn(user_email, agent["id"], history,
                                   tool_ids=tool_ids)
                   if tool_ids is not None
                   else await _run_turn(user_email, agent["id"], history))
        finally:
            _listing_for_turn.reset(reset)
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


#: The longest message Jev is asked to read as a goodbye. "ok thanks, I'm
#: done with Dev for now" is eight words; longer is a request to the agent.
RELEASE_MAX_WORDS = 8


async def _jev_release(key: str, email: str, text: str) -> bool:
    """Whether Jev is sure a short message to an awake agent sends it back
    to sleep. Asked only with a key, about a message of at most
    RELEASE_MAX_WORDS words, in a chat with an agent pinned: everything else
    costs no call and no wait. Never raises."""
    try:
        words = len((text or "").split())
        if not (0 < words <= RELEASE_MAX_WORDS and agent_decider.enabled()):
            return False
        if await _read_pin(key) is None:
            return False
        return await agent_jev.wants_release(email, text) is True
    except Exception:                                       # noqa: BLE001
        logger.warning("could not ask Jev about a release", exc_info=True)
        return False


#: Words that are a greeting or a pleasantry and nothing else. A message made
#: up only of these has no subject in it to hand anyone and no tool to pick
#: for it, so Jev is not asked and the free model answers, which it does well.
#:
#: This replaces a word count of four, changed 2026-10-29. The count was
#: aimed at "hi" and "thanks" but it caught the shortest REAL requests along
#: with them: "check my inbox" is three words, "any new email" is three, "read
#: my emails" is three. Every one of them skipped the tool pick and went to a
#: model with no mailbox, which is the single thing this chat is most often
#: asked to do. Length was never what distinguished a greeting from a request;
#: the words are.
_PLEASANTRIES = frozenset({
    "hi", "hey", "hello", "heya", "hiya", "yo", "sup", "greetings",
    "morning", "afternoon", "evening", "night", "good", "day",
    "thanks", "thank", "thankyou", "thx", "ty", "ta", "cheers", "appreciate",
    "ok", "okay", "k", "kk", "cool", "nice", "great", "perfect", "awesome",
    "lovely", "lol", "haha", "hah", "yay",
    "bye", "goodbye", "later", "cya", "ciao",
    "yes", "yeah", "yep", "yup", "no", "nope", "nah", "sure", "fine",
    "please", "pls", "sorry", "welcome",
    "you", "u", "your", "there", "it", "that", "me", "my", "all", "and",
    "mate", "man", "buddy", "friend", "team", "everyone",
})


def is_small_talk(text: str) -> bool:
    """A greeting or a pleasantry with no request in it.

    True only when EVERY word is a pleasantry, so "thanks" and "good morning
    everyone" skip Jev while "thanks, check my inbox" does not: one word that
    is not on the list is enough to make it a message about something.
    """
    words = re.findall(r"[a-z']+", (text or "").lower())
    return bool(words) and all(w in _PLEASANTRIES for w in words)

#: In the MAIN CHAT, an agent answers only when the person named it.
#:
#: Asked for on 2026-10-28, with a screenshot: "what is the richest man in the
#: world" was handed to Vera. That was not a bug in the routing, it was the
#: routing working as built. The row is in tasks.agent_decision: Jev read it as
#: a research question and picked Vera (the Researcher) at 0.92 confidence,
#: path=one_agent. Reasonable from Jev's side; wrong from the person's, who had
#: named nobody and wanted the free model.
#:
#: So in the main chat the three rungs that reach an agent WITHOUT a mention
#: are off: Jev's pick, the skill owner, and the subject owner. Naming an agent
#: still does everything it did, and so does a follow-up to one just named
#: (the pin), because "yes, do that" has to reach whoever was asked.
#:
#: The PANEL and the office are untouched. Asking the room is what that surface
#: is for, and nobody there is surprised to hear from an agent.
#:
#: One switch, so it is one line to put back: AGENTS_ANSWER_UNNAMED=1.
def _agents_may_take_unnamed() -> bool:
    return os.environ.get("AGENTS_ANSWER_UNNAMED", "0").strip().lower() in (
        "1", "true", "yes", "on")


async def _none():
    """Nothing, as an awaitable, so the gather above keeps one shape."""
    return None


async def _jev_decision(body: ChatIn, text: str, agents: list[dict]) -> dict | None:
    """The agent Jev is sure should take this message, or None. Never
    raises: Jev is a bonus on top of a working chat."""
    try:
        if not agent_decider.enabled():
            return None
        if is_small_talk(text):
            return None
        decision = await agent_decider.decide(body.user_email, body.chat_id, text,
                                              body.messages, agents)
        if decision is None or decision.path != agent_decider.PATH_ONE_AGENT:
            return None
        return next((a for a in agents
                     if str(a.get("id") or "") == decision.agent_id), None)
    except Exception:                                       # noqa: BLE001
        logger.warning("Jev could not pick an agent for the chat; answering as "
                       "before", exc_info=True)
        return None


async def _jev_pick(body: ChatIn, text: str, agents: list[dict]) -> dict | None:
    """The finished response when Jev is sure one agent should take this
    message and that agent's reply answers it, else None."""
    agent = await _jev_decision(body, text, agents)
    if agent is None:
        return None
    return await _jev_answer(body, text, agents, agent)


async def _jev_answer(body: ChatIn, text: str, agents: list[dict],
                      agent: dict) -> dict | None:
    """The agent Jev chose answering, when its reply holds up, else None.
    Never raises."""
    try:
        names = [a.get("name") for a in agents if a.get("name")]
        # Said before the turn, not after: the turn is the slow part, and
        # the whole point is that the wait stops being silent. Jev's pick
        # is a real fact about this message, so naming the agent here is
        # honest even though the reply may still be discarded below.
        agent_progress.say(agent_progress.answering_line([agent.get("name")]))
        turn = await _turn_for(body.user_email, agent, body.messages, names,
                               roster=agents,
                               graph=await agent_graph.graph_block(
                                   body.user_email, text))
        # A reply that did not answer is not shown: the general model gets
        # the message instead, as it would have without Jev. A question the
        # agent stopped to ask (pending) is an answer in progress and stays.
        pending = isinstance(turn.get("pending"), dict) and bool(turn["pending"].get("calls"))
        if not pending:
            ok = await agent_jev.reply_answers(body.user_email, text,
                                               str(turn.get("answer") or ""))
            if ok is False:
                return None
        await _write_pin(_pin_key(body.chat_id, body.user_email), agent["id"])
        return _reply([turn], queue=[], marker="",
                      status=agent_progress.answered_by([agent.get("name")]))
    except Exception:                                       # noqa: BLE001
        logger.warning("Jev could not pick an agent for the chat; answering as "
                       "before", exc_info=True)
        return None


#: Turns of the conversation Jev is shown behind the latest message. Enough
#: for a follow-up to inherit its subject, few enough that an old topic
#: cannot outweigh the current one.
CONTEXT_TURNS = 6


def recent_exchange(messages, turns: int = CONTEXT_TURNS) -> str:
    """What was said just before the latest message, as plain lines.

    Jev used to be shown one orphan sentence, so "create it please" carried
    no subject and no tool was picked. Measured live on 2026-10-29: the same
    person's "make a daily quote agent" picked agent_builder and schedules
    at 0.89, and their very next message, "create it please", picked nothing
    at 0.34. The assistant never ran and the free model answered "I can't
    actually create agents or scheduled cron jobs inside your platform",
    which is the product denying its own feature at the moment it was asked
    for. Agreement is always the shortest message, so this failed hardest
    exactly when somebody said go.

    The latest message is EXCLUDED: the caller passes that separately as the
    thing being judged, and repeating it would weight it twice.
    """
    out = []
    for m in list(messages or [])[-(turns + 1):-1]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        said = agent_routing.last_user_text([dict(m, role="user")])
        said = " ".join(str(said or "").split())
        if said:
            out.append("%s: %s" % ("person" if role == "user" else "reply",
                                   said[:400]))
    return "\n".join(out)


def _assistant_on() -> bool:
    """MAIN_ASSISTANT=0 switches the assistant off; anything else is on."""
    return os.environ.get("MAIN_ASSISTANT", "1").strip() != "0"


#: Answers that mean the assistant's turn did not work. The pipe's own free
#: model answers instead, which is what happened before the assistant.
def _assistant_failed(answer: str) -> bool:
    answer = (answer or "").strip()
    return (not answer
            or answer == _turn_failed_sentence(main_assistant.NAME)
            or answer in (FREE_POOL_EXHAUSTED, ROUTER_EXHAUSTED,
                          AGENT_ON_CALLBACK_MODEL))


async def _tool_pick(body: ChatIn, text: str) -> list[str] | None:
    """The tools Jev is sure this message needs for the assistant: a list
    (maybe empty) or None when the assistant is off, the message is a
    greeting, the assistant cannot run, or Jev could not be asked. Never
    raises."""
    try:
        if not _assistant_on():
            return None
        if is_small_talk(text):
            return None
        if not agent_llm.can_run(main_assistant.agent()):
            return None
        tools = await _every_tool_for(body.user_email)
        if not tools:
            return None
        return await agent_jev.pick_tools(body.user_email, text, tools,
                                          recent_exchange(body.messages))
    except Exception:                                       # noqa: BLE001
        logger.warning("the main chat's tool pick failed; the free model "
                       "answers instead", exc_info=True)
        return None


async def _assistant_reply(body: ChatIn, text: str, agents: list[dict],
                           picked: list[str] | None = None) -> dict | None:
    """The main chat's assistant answering a message nobody took, with the
    tools Jev picked for it, or None to leave it to the caller's own model.
    Never raises.

    Only with a tool to use (2026-10-28, "if nothing is mentioned, just
    answer"): an ordinary question is the free model's, at once, with no
    brief, no graph read and no tool loop in front of it. Jev sure that no
    tool is needed, or Jev unavailable, both mean the free model answers;
    an agent named by the person still has everything it has.
    """
    try:
        if picked is None:
            picked = await _tool_pick(body, text)
        if not picked:
            return None
        assistant = main_assistant.agent()
        names = [a.get("name") for a in agents if a.get("name")]
        # The slowest thing the main chat does, and until now the most
        # silent: "check my inbox" took 9.5s on the live box with nothing
        # on screen. Said before the turn, naming the place rather than the
        # tool id, and no agent's name, because no agent is involved.
        agent_progress.say(agent_progress.reading_line(picked))
        turn = await _turn_for(
            body.user_email, assistant, body.messages, names, roster=agents,
            graph=await agent_graph.graph_block(body.user_email, text),
            tool_ids=list(picked))
        pending = (isinstance(turn.get("pending"), dict)
                   and bool(turn["pending"].get("calls")))
        if not pending and _assistant_failed(str(turn.get("answer") or "")):
            return None
        # IO speaking for itself: no name and no face over the answer, and
        # that holds whether it answered or stopped to ask.
        #
        # It used to hold only when it answered, so a turn that stopped for
        # approval kept the assistant's agent row and the chat drew the
        # office robot and a bold "IO" above it. Reported 2026-10-29 with a
        # screenshot: "i havnet mention any agent why is this". Exactly the
        # complaint from 2026-10-28 that put this line here in the first
        # place, surviving in the one branch it was never applied to. The
        # assistant is the free model with the tools Jev picked; nobody was
        # named, so nobody is shown.
        #
        # Safe for the approval itself: what resumes a held call is
        # pending["agent_id"], never turn["agent"], which is only ever a
        # display name.
        turn = dict(turn, agent=None)
        # What it read, left on screen. An answer built from the person's
        # own mailbox used to be indistinguishable from one the model made
        # up, which is the difference between information and a guess.
        return _reply([turn], queue=[], marker="",
                      status=agent_progress.used_line(picked))
    except Exception:                                       # noqa: BLE001
        logger.warning("the main chat's assistant could not answer; the free "
                       "model answers instead", exc_info=True)
        return None


@router.post("/chat")
async def chat(body: ChatIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Who should answer this message (_route_chat), plus Yes/No in the
    main chat: on Auto (route_only), a turn that stops to ask is held, and
    the next message, if it is a bare yes or no from the same person,
    resumes exactly that call (2026-10-27). Anything else drops it.

    Only on Auto. Discord, Slack and Telegram hold their own questions and
    resume them from their own buttons; holding it here as well could run
    one approved call twice.
    """
    _require_internal(x_internal_secret)
    # Every caller of this route is the main chat, so the mark goes here
    # rather than being inferred from the body further in. It makes the run
    # rows say "chat" instead of "channel", which is what makes the main
    # chat measurable at all (agent_activity.main_chat).
    with agent_activity.main_chat():
        return await _chat_inner(body, x_internal_secret)


async def _chat_events(body: ChatIn, x_internal_secret: str):
    """The same work as `chat`, as a stream: each progress line as it
    happens, then the reply `chat` would have returned.

    Why a second route rather than a flag on the first: /agents/chat has
    three callers and two of them (io_gateway_pipe, agents_tool) want one
    JSON object and nothing else. A streaming response is a different
    contract, so it gets a different path, and a caller that has not been
    taught about it is unaffected.

    The turn runs as a task and the queue is drained beside it, which is
    what lets a line reach the person while the tool loop it describes is
    still going. A failure here must cost the status lines and never the
    answer, so the task's exception is re-raised to the caller exactly as
    the plain route would raise it.
    """
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def work():
        try:
            with agent_activity.main_chat(), \
                    agent_progress.reporting_to(queue.put_nowait):
                return await _chat_inner(body, x_internal_secret)
        finally:
            queue.put_nowait(done)

    task = asyncio.create_task(work())
    # If the person closes the tab mid-turn, sse_starlette closes this
    # generator and nobody is left to await the task. The turn is NOT
    # cancelled, deliberately: it may be halfway through sending an email,
    # and a half-done tool call is worse than an answer nobody reads. This
    # just collects the result so a failure after the reader has gone does
    # not surface as "Task exception was never retrieved".
    task.add_done_callback(lambda t: t.cancelled() or t.exception())
    try:
        while True:
            item = await queue.get()
            if item is done:
                break
            yield {"event": "status", "data": json.dumps({"line": str(item)})}
        reply = await task
    except Exception:                                       # noqa: BLE001
        logger.warning("the main chat's streamed turn failed", exc_info=True)
        yield {"event": "error", "data": "{}"}
        return
    yield {"event": "reply", "data": json.dumps(reply)}


@router.post("/chat/stream")
async def chat_stream(body: ChatIn,
                      x_internal_secret: str = Header(default="")
                      ) -> EventSourceResponse:
    """`chat`, with the progress lines sent as they happen.

    The main chat used to go silent for the whole turn: 9.5s for "check my
    inbox" and 12.3s for an attachment an agent took, measured live on
    2026-10-29, with nothing on screen. This is how the pipe learns what to
    say during that wait.

    It does NOT stream the answer, on purpose. `agent_jev.reply_answers` can
    decide an agent's reply did not answer the question, and then it is
    discarded and the free model answers instead; `_assistant_failed` does
    the same for the assistant. Text that might still be thrown away must
    not already be on the person's screen.
    """
    _require_internal(x_internal_secret)
    # sse_starlette rather than a hand-rolled StreamingResponse, to match
    # the panel's stream (routes_agent_chat) and to get its ping, which is
    # what keeps a long tool loop from looking like a dead connection.
    # X-Accel-Buffering because a buffered event stream arrives all at once
    # at the end, which is exactly the silence this route exists to remove.
    return EventSourceResponse(
        _chat_events(body, x_internal_secret),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _chat_inner(body: ChatIn, x_internal_secret: str) -> dict:
    """The body of `chat`, so the main chat mark wraps all of it."""
    if not getattr(body, "route_only", False):
        return await _route_chat(body, x_internal_secret)
    key = _pending_key(_pin_key(body.chat_id, body.user_email))
    held = await _read_pending(key)
    text = agent_routing.last_user_text(body.messages)
    answer = agent_routing.answers_yes_or_no(text)
    if held is not None:
        await _clear_pending(key)
        same_person = (str(held.get("user_email") or "").lower()
                       == (body.user_email or "").lower())
        if answer is not None and same_person and held.get("agent_id"):
            # The question has a row too (agent_approvals): settled first,
            # so an answer already given on the Agents page is not run a
            # second time here.
            row_id = str(held.get("approval_id") or "")
            if row_id and not await agent_approvals.settle(
                    body.user_email, row_id, answer, agent_approvals.VIA_CHAT):
                return _reply([{"agent": None, "answer": ALREADY_ANSWERED,
                                "notes": []}], queue=[], marker="")
            out = await _resume_held(body, held, answer)
            if out is not None:
                return out
    elif answer is not None:
        # Nothing held in this chat, but a bare yes or no may be for a
        # question asked somewhere else: an automation's agent, or another
        # chat. One waiting question is answered; more than one is listed,
        # since "yes" says nothing about which.
        out = await _answer_waiting(body, answer)
        if out is not None:
            return out
    out = await _route_chat(body, x_internal_secret)
    for turn in out.get("turns") or []:
        if _held(turn):
            pending = dict(turn["pending"])
            who = turn.get("agent") if isinstance(turn.get("agent"), dict) else {}
            # The assistant carries no agent row by design, so without this
            # both the Agents page and the stored question would fall back
            # to its raw id and read "io-assistant wants to run:". The page
            # still needs to say where the question came from, and the
            # honest answer is the main chat rather than any agent.
            held_by = str(pending.get("agent_id") or "")
            asked_by = who.get("name")
            shown_as = (asked_by or ("Main chat"
                                     if main_assistant.is_assistant(held_by)
                                     else held_by))
            row = await agent_approvals.hold(
                body.user_email, held_by, shown_as, pending,
                agent_approvals.ORIGIN_CHAT, key,
                approval_question(asked_by if asked_by
                                  else (None if main_assistant.is_assistant(held_by)
                                        else held_by),
                                  pending.get("calls") or []))
            if row:
                pending["approval_id"] = row["id"]
            await _write_pending(key, pending)
            break
    return out


#: Said when a yes or no arrives for a question answered elsewhere already.
ALREADY_ANSWERED = "That was already answered, so nothing more was done."


async def _answer_waiting(body: ChatIn, approved: bool) -> dict | None:
    """A bare yes or no with nothing held in this chat: the one question
    waiting elsewhere, or a list of them. None when nothing waits and the
    message goes on to be routed as usual."""
    waiting = await agent_approvals.pending_for(body.user_email)
    if not waiting:
        return None
    if len(waiting) > 1:
        lines = ["More than one question is waiting, so I did not guess which "
                 "you meant:"]
        for w in waiting:
            lines.append("- %s: %s" % (w.get("agent_name") or w.get("agent_id"),
                                       (w.get("question") or "").split("\n")[0]))
        lines.append("Answer them on the Agents page under Automation.")
        return _reply([{"agent": None, "answer": "\n".join(lines), "notes": []}],
                      queue=[], marker="")
    import routes_approvals
    out = await routes_approvals.decide(body.user_email, waiting[0]["id"], approved,
                                        agent_approvals.VIA_CHAT)
    turn = {"agent": out.get("agent"), "answer": out.get("answer") or "",
            "notes": out.get("notes") or []}
    return _reply([turn], queue=[], marker="")


async def _resume_held(body: ChatIn, held: dict, approved: bool) -> dict | None:
    """The held call, run or refused as the person said, as a reply. None
    when it could not be resumed, and the message is routed as usual."""
    agent_id = str(held.get("agent_id"))
    try:
        result = await _resume_turn(
            user_email=body.user_email, agent_id=agent_id,
            conversation=held.get("conversation") or [],
            calls=held.get("calls") or [], approved=approved)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not resume the held approval", exc_info=True)
        return None
    if main_assistant.is_assistant(agent_id):
        who = {"id": agent_id, "name": main_assistant.NAME}
    else:
        agents = await _agents_for(body.user_email)
        row = next((a for a in agents if str(a.get("id") or "") == agent_id), {})
        who = {"id": agent_id, "name": row.get("name") or agent_id}
    turn = dict(result, agent=who)
    if not _held(turn) and main_assistant.is_assistant(agent_id):
        turn["agent"] = None
    return _reply([turn], queue=[], marker="")


async def _route_chat(body: ChatIn, x_internal_secret: str = "") -> dict:
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
    forced = str(getattr(body, "agent_id", None) or "").strip()

    if not forced and (agent_routing.wants_release(text)
                       or await _jev_release(key, body.user_email, text)):
        await _clear_pin(key)
        turns = [{"agent": None, "answer": RELEASED, "notes": []}]
        return _reply(turns, queue=[], marker="")

    agents = await _agents_for(body.user_email)
    if forced:
        # The message was sent to this agent's own model: it is the one
        # addressed, as surely as a name at the start of the sentence.
        named = [a for a in agents if str(a.get("id") or "") == forced]
        if not named:
            turns = [{"agent": None, "answer": NOT_YOUR_AGENT, "notes": []}]
            return _reply(turns, queue=[], marker="")
    else:
        named = agent_routing.match_agents(text, agents)

    if named:
        # Naming agents switches rather than stacking: the LAST one named is
        # who a follow up with no name goes to, so "actually ada, you take
        # this" hands over cleanly even when Mia was also named.
        names = [a.get("name") for a in agents if a.get("name")]
        # Once for the message, not once per agent: naming two agents runs two
        # turns about one question, and the account has not changed between
        # them.
        graph, now = await asyncio.gather(
            agent_graph.graph_block(body.user_email, text),
            clock_for(body.user_email))
        speakers = named[:1] if getattr(body, "first_only", False) else named
        # Each agent is announced as its own turn starts, not all at once
        # up front: they run one at a time (3.8GB box), so saying all three
        # names immediately would claim work that has not begun.
        turns = []
        for agent in speakers:
            agent_progress.say(
                agent_progress.answering_line([agent.get("name")]))
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
        spoke = agent_progress.answered_by([a.get("name") for a in speakers])
        if first_pending:
            await _write_pin(key, named[0]["id"])
            return _reply(turns, queue=queue, marker=turns_marker(ids),
                          status=spoke)
        await _write_pin(key, named[-1]["id"])
        return _reply(turns, queue=queue, marker=turns_marker(ids),
                      status=spoke)

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
        # A skill asked for by name ("run the weekly review") is a job for
        # the one agent that was given it: its steps are in that agent's
        # brief and in nobody else's. Two agents with the skill leave it to
        # Jev below. Above the subject rung, as in the ladder:
        # "weekly" is also a schedules word. Read from disk through a cache, so this costs nothing.
        # Not in the main chat unless the owner turned it back on: a skill
        # name is still not a mention.
        if not (getattr(body, "route_only", False)
                and not _agents_may_take_unnamed()):
            skilled = agent_routing.skill_owner(text, agents,
                                                agent_skills.load_all())
            if skilled is not None:
                agent = skilled

    if agent is None:
        # Nobody named and nobody pinned. Before handing this to IO, the same
        # ladder the panel uses gets a look: if exactly one agent owns the
        # subject, "anything unread in my inbox" is a question for the one
        # agent with the mailbox, not a question for a general model that
        # cannot see it. Only when it is unambiguous, so a room where two
        # agents read email still falls through.
        # Same in the main chat. This is the rung with a real cost: "anything
        # unread in my inbox" now goes to a model that cannot read the inbox.
        # Naming the agent still works, and so does AGENTS_ANSWER_UNNAMED=1.
        if not (getattr(body, "route_only", False)
                and not _agents_may_take_unnamed()):
            owner = agent_routing.domain_owner(text, agents)
            if owner is not None:
                agent = owner

    if agent is None:
        # Nobody named, pinned or obviously owning the subject. Before the
        # general model answers, Jev (agent_decider) is asked whether this
        # is one agent's to take, and which: "chase the overdue invoices"
        # with a Finance agent on the team goes to Finance rather than to a
        # free model that cannot see the books. Only when Jev is sure, and
        # only when the reply then answers the message (agent_jev): a pick
        # that did not pan out costs the person nothing but a moment, and
        # the message goes on exactly as before. This is what puts Jev in
        # the main chat (2026-10-26): the Auto pipe asks here first.
        if getattr(body, "route_only", False):
            # On Auto the two questions Jev is asked, "is this one agent's"
            # and "which tools would the assistant need", do not depend on
            # each other, so they are asked side by side (2026-10-28): one
            # wait, not two. Nothing picked either way means the free model
            # answers at once, which is what an ordinary question deserves.
            # _tool_pick still runs: it picks TOOLS for the assistant, which
            # is the free model with hands, not an agent speaking as itself.
            chosen, picked = await asyncio.gather(
                (_jev_decision(body, text, agents) if _agents_may_take_unnamed()
                 else _none()),
                _tool_pick(body, text))
            if chosen is not None:
                answered = await _jev_answer(body, text, agents, chosen)
                if answered is not None:
                    return answered
            helped = await _assistant_reply(body, text, agents, picked=picked)
            if helped is not None:
                return helped
        else:
            picked = await _jev_pick(body, text, agents)
            if picked is not None:
                return picked

    if agent is None and getattr(body, "route_only", False):
        # The caller will answer for itself. Saying so with an empty list
        # rather than an IO answer is what keeps the Auto pipe from asking
        # IO, which would ask Auto, which would ask here again.
        return _reply([], queue=[], marker="")

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
        return _reply(turns, queue=[], marker="")

    # A follow up keeps the agent awake. Without this the pin would run out
    # five minutes after the agent was last NAMED, mid conversation.
    names = [a.get("name") for a in agents if a.get("name")]
    # The pinned agent, the skill owner or the subject owner: the person
    # did not name anybody this time, so saying who picked the message up
    # matters more here than where they did.
    agent_progress.say(agent_progress.answering_line([agent.get("name")]))
    turn = await _turn_for(body.user_email, agent, body.messages, names,
                           roster=agents,
                           graph=await agent_graph.graph_block(
                               body.user_email, text))
    await _write_pin(key, agent["id"])
    return _reply([turn], queue=[], marker="",
                  status=agent_progress.answered_by([agent.get("name")]))
