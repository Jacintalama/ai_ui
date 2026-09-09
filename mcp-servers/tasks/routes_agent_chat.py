"""The agent chat panel on the AI Agents page.

One message, one answer per agent in the room, each in its own bubble. The
panel draws its own messages, so a reply being its own message is not a trick
played on somebody else's renderer, which is what the previous attempt was and
why it failed.

Shape copied from routes_fusion_page: server-rendered fragments, vendored
HTMX, a per-user in-memory working session over a durable row, and one SSE
stream per turn. All routes sit under /tasks, already routed to this service
end to end, so nothing outside this service changes.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

import agent_chat_render as render
import agent_chat_store as store
from auth import CurrentUser, current_user
import agent_access
import agent_routing
from agent_runner import CHANNEL_HTTP_TIMEOUT_SECONDS, _chat
from routes_agent_turn import (_agents_for, _resolve_agent,
                               _resume_turn, _turn_for)
from routes_agents import _pending_for_page

log = logging.getLogger(__name__)

router = APIRouter()

#: Roughly how much conversation a round hands each agent, in characters.
#: Everything fits until it does not: the point of one permanent room is that
#: an agent still knows what was said this morning. When the conversation
#: outgrows this, the oldest part is summarised rather than thrown away, so
#: the words go but the sense stays.
HISTORY_BUDGET_CHARS = 24000

#: How much of the budget a summary is allowed to take back.
SUMMARY_BUDGET_CHARS = 4000

#: What an agent says when it has nothing to add. A pass costs one model call
#: and produces no bubble, which is the price of everybody listening.
PASS_TOKEN = "PASS"

#: Given to an agent nobody named. Everyone hears every message; only the ones
#: with something worth saying answer.
PASS_INSTRUCTION = (
    "You are one of several assistants in this room, and the message above was "
    "not addressed to you by name. Everyone heard it. Answer if you can "
    "genuinely help with it, or if you know something about it the others "
    "would miss. If you have nothing worth saying, reply with exactly PASS and "
    "nothing else.")

#: Asked of one agent when the conversation outgrows the budget.
SUMMARY_INSTRUCTION = (
    "Summarise the conversation above for your own future reference. Keep what "
    "was decided, what the person asked for, any names, numbers and "
    "commitments, and anything still open. Drop pleasantries. Write it as "
    "notes, not as a reply to anybody.")


def _ask_id() -> str:
    """A name for one question an agent asked.

    Not the agent's id. The same agent can be waiting on two answers at once
    if a second message goes out while the first question is unanswered, and
    keying on the agent would have the second overwrite the first: a held
    conversation discarded without anybody being told, and two Yes buttons on
    the page pointing at the same element.
    """
    return uuid.uuid4().hex


def _turns_of(messages: list[dict]) -> list[dict]:
    """The conversation as a model should see it: role and content only.

    agent_id and agent_name are ours, for drawing the bubbles, and mean
    nothing to a model. Empty turns are dropped because empty content is
    rejected upstream, and bookkeeping roles fall out here too.
    """
    out = []
    for m in messages or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def _weight(turns: list[dict]) -> int:
    return sum(len(t.get("content") or "") for t in turns)


def _split_for_budget(turns: list[dict]) -> tuple[list[dict], list[dict]]:
    """(what to summarise, what to send verbatim).

    Walks back from the newest turn, keeping whole turns until the budget is
    spent. The message being answered is the point of the round, so it is
    never on the wrong side of the split however long it is.
    """
    if _weight(turns) <= HISTORY_BUDGET_CHARS:
        return [], list(turns)
    keep: list[dict] = []
    spent = 0
    for turn in reversed(turns):
        cost = len(turn.get("content") or "")
        if keep and spent + cost > HISTORY_BUDGET_CHARS:
            break
        keep.append(turn)
        spent += cost
    keep.reverse()
    older = turns[:len(turns) - len(keep)]
    # Widen to the newest user message if the split landed above it.
    newest_user = max((i for i, t in enumerate(turns) if t["role"] == "user"),
                      default=None)
    if newest_user is not None and newest_user < len(older):
        keep = turns[newest_user:]
        older = turns[:newest_user]
    return older, keep


def _history_for_round(messages: list[dict], summary: str = "") -> list[dict]:
    """The conversation every agent in this round sees. Built ONCE.

    A summary of everything older rides in front as an ordinary assistant
    turn, because that is a shape every backend accepts and it reads to the
    model as something already known rather than as an instruction.
    """
    _, keep = _split_for_budget(_turns_of(messages))
    if not summary:
        return keep
    head = {"role": "assistant",
            "content": "Notes on everything said earlier:\n" + summary}
    return [head] + keep


def _drop(messages: list[dict], marker: dict) -> None:
    """Remove `marker` by identity.

    Not list.remove, which matches by equality: two empty bookkeeping dicts
    compare equal, so remove() can delete the wrong one.
    """
    for i, m in enumerate(messages):
        if m is marker:
            del messages[i]
            return


def _clear_awaiting(messages: list[dict], ask_id: str) -> None:
    """Take one answered question off the stored message, so a replayed
    conversation does not offer Yes and No on something already decided.

    Matched on the question, not on the agent: an agent with two questions
    outstanding must not have both of them cleared by one answer.
    """
    for m in messages:
        awaiting = m.get("awaiting")
        if isinstance(awaiting, dict) and awaiting.get("ask_id") == ask_id:
            m.pop("awaiting", None)


def _name_for(agent_id: str, agents: list[dict]) -> str:
    for a in agents:
        if str(a.get("id")) == agent_id:
            return str(a.get("name") or agent_id)
    return agent_id


def _is_pass(answer: str) -> bool:
    """An agent declining to speak.

    Generous about the shape because models are: a bare PASS, a PASS with a
    full stop, a PASS in quotes. Anything longer is an answer that happens to
    contain the word.
    """
    stripped = (answer or "").strip().strip('."\'').upper()
    return stripped == PASS_TOKEN


def _speakers_for(text: str, agents: list[dict]) -> tuple[list[dict], bool]:
    """Who answers this message, and whether they are allowed to pass.

    Naming an agent is how you ask one of them something: the named ones
    answer, and they answer because you asked, so they may not pass. Naming
    nobody is the ordinary case, and then everybody in the room hears it and
    each decides for itself whether it has anything to add.

    match_agents is the same routing the channels use, so asking for Mia in
    the panel and asking for Mia in Discord pick the same agent.
    """
    named = agent_routing.match_agents(text, agents)
    if named:
        return named, False
    return list(agents), True


def _last_speaker(messages: list[dict], agents: list[dict]) -> dict | None:
    """The agent that answered most recently, if it is still one of these.

    Used only when everybody passed. Carrying on with whoever was already
    talking is a better guess than always falling back to the same one.
    """
    by_id = {str(a.get("id")): a for a in agents}
    for m in reversed(messages or []):
        if m.get("role") == "assistant" and m.get("agent_id") in by_id:
            return by_id[str(m["agent_id"])]
    return None


async def _summarise(email: str, agent: dict, turns: list[dict]) -> str:
    """Fold the oldest turns into notes the room keeps.

    Runs with tools off and a single iteration: this is a reading job, and a
    summariser that could send an email is a summariser that one day does.
    Never raises. A conversation that cannot be summarised is one that gets
    trimmed instead, which is worse but not broken.
    """
    if not turns:
        return ""
    try:
        token, _tools, _level = await _resolve_agent(email, agent["id"])
        answer, _notes = await _chat(
            token=token, model=agent["id"],
            messages=list(turns) + [{"role": "user",
                                     "content": SUMMARY_INSTRUCTION}],
            tool_ids=None, user_email=email,
            tool_mode=agent_access.MODE_READ_ONLY,
            refusal_reason="summarising does not run tools",
            max_iterations=1, timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
    except Exception:                                       # noqa: BLE001
        logger.warning("agent chat: could not summarise the older turns",
                       exc_info=True)
        return ""
    return (answer or "").strip()[:SUMMARY_BUDGET_CHARS]


async def _keep_within_budget(email: str, s: store.RoomSession,
                              agents: list[dict]) -> None:
    """Summarise the oldest turns once the conversation outgrows the budget.

    Called before the round rather than after, so the agents answering this
    message are the ones reading the notes. The summary replaces nothing on
    screen: the person keeps the whole conversation, the agents get the notes
    plus the recent turns.
    """
    turns = _turns_of(s.messages)
    older, _keep = _split_for_budget(turns)
    if not older or not agents:
        return
    previous = ("Notes so far:\n" + s.summary + "\n\n") if s.summary else ""
    fresh = await _summarise(email, agents[0],
                             [{"role": "assistant", "content": previous}] + older
                             if previous else older)
    if fresh:
        s.summary = fresh
        s.summarised_upto = len(turns) - len(_keep)


async def _run_round(email: str, s: store.RoomSession, agents: list[dict],
                     request: Request | None = None):
    """Yield one SSE event per thing that happens in a round.

    Agents run one at a time, never in parallel: a turn can run tools and this
    box has 3.8GB of RAM.
    """
    names = [a.get("name") for a in agents if a.get("name")]
    # Who speaks is decided from the message, not from a room the person had
    # to build first. Name an agent and only that agent answers; name nobody
    # and everybody hears it and decides for itself.
    asked = agent_routing.last_user_text(s.messages)
    speakers, may_pass = _speakers_for(asked, agents)
    # Built once, before the first agent runs, and handed unchanged to every
    # agent. See the module docstring of routes_agent_turn for what happens
    # when agents read each other's labelled replies.
    history = _history_for_round(s.messages, s.summary)
    # Bound once, alongside history, and written to for the rest of the round
    # instead of going through s. each time. _turn_for is a real outbound
    # call, so the event loop can service another request from the same
    # person while one is in flight. New chat and Delete now replace
    # s.messages / s.pending with fresh objects rather than clearing them in
    # place, precisely so that a round keeps appending into the buffer it
    # started with: a reset mid-round detaches this round's buffer, it does
    # not redirect it into whatever conversation is open by the time the
    # round finishes.
    messages = s.messages
    pending = s.pending

    # An agent that heard the message and had nothing to add. Counted so the
    # round can tell "nobody had anything" from "nobody was asked".
    passed = 0

    for agent in list(speakers):
        if request is not None and await request.is_disconnected():
            break
        agent_id = str(agent.get("id") or "")
        name = str(agent.get("name") or agent_id)
        yield {"event": "working", "data": render.working(name)}
        turn_history = history
        if may_pass:
            turn_history = history + [{"role": "user",
                                       "content": PASS_INSTRUCTION}]
        out = await _turn_for(email, agent, turn_history, names)
        answer = out.get("answer") or ""

        if may_pass and _is_pass(answer) and not out.get("pending"):
            # It listened and had nothing to say. No bubble, nothing stored:
            # a pass should leave no trace except the cost of asking.
            passed += 1
            continue

        raw_pending = out.get("pending")
        page_pending = (_pending_for_page(raw_pending)
                        if isinstance(raw_pending, dict) else None)
        if page_pending:
            # Hold the full payload server side: it carries the held
            # conversation and the owner's email, neither of which belongs in
            # a browser. The browser gets the calls only.
            #
            # Keyed by the question, not by the agent. One agent can be
            # waiting on two answers at once, and keying by the agent would
            # have the second question quietly replace the first.
            ask_id = _ask_id()
            pending[ask_id] = raw_pending
            awaiting = dict(page_pending)
            awaiting["ask_id"] = ask_id
            messages.append({"role": "assistant", "agent_id": agent_id,
                             "agent_name": name, "content": answer,
                             "awaiting": awaiting})
            if answer:
                yield {"event": "message",
                       "data": render.agent_bubble(name, answer)}
            yield {"event": "message",
                   "data": render.approval_bubble(name, ask_id,
                                                  page_pending["calls"])}
            # And on to the next agent. Pausing the one that asked is the
            # point; silently losing everybody else is not.
            continue

        messages.append({"role": "assistant", "agent_id": agent_id,
                         "agent_name": name, "content": answer})
        yield {"event": "message", "data": render.agent_bubble(name, answer)}

    if speakers and passed == len(speakers):
        # Everybody passed, which leaves the person talking to an empty room.
        # Ask the one who spoke last, or the first, and this time without the
        # option of passing. One extra call, and only in this case.
        fallback = _last_speaker(s.messages, speakers) or speakers[0]
        name = str(fallback.get("name") or fallback.get("id") or "")
        yield {"event": "working", "data": render.working(name)}
        out = await _turn_for(email, fallback, history, names)
        answer = out.get("answer") or ""
        if answer and not _is_pass(answer):
            messages.append({"role": "assistant",
                             "agent_id": str(fallback.get("id") or ""),
                             "agent_name": name, "content": answer})
            yield {"event": "message", "data": render.agent_bubble(name, answer)}
        else:
            # It passed again even without being offered the option. Say so
            # rather than leave the room silent: a person who typed something
            # and got nothing back cannot tell that from a broken panel.
            line = "Nobody had anything to add to that."
            messages.append({"role": "note", "content": line})
            yield {"event": "message", "data": render.note(line)}

    if not agents:
        line = ("You have no agents yet. Make one and it will hear the next "
                "thing you say.")
        messages.append({"role": "note", "content": line})
        yield {"event": "message", "data": render.note(line)}

    yield {"event": "working", "data": ""}


def _take_queued(s: store.RoomSession):
    """The next message typed while the agents were answering, or None.

    Removes what it returns. Leaving it in place would have the same question
    answered on every round for the rest of the session.
    """
    return s.queued.pop(0) if s.queued else None


async def _hydrate(email: str, s: store.RoomSession) -> None:
    """Load this person's one conversation into a session that has none.

    The room is permanent, so a reload, a new tab or a service restart should
    put somebody back where they were rather than in front of an empty panel
    holding a conversation the database still has.

    Only ever fills an empty session: a session with messages in it is the
    working copy and is ahead of the row.
    """
    if s.chat_id is not None or s.messages:
        return
    try:
        row = await store.newest_chat(email)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not load the conversation")
        return
    if not row:
        return
    s.chat_id = str(row["id"])
    s.messages = list(row.get("messages") or [])
    s.pending = dict(row.get("pending") or {})
    s.summary = str(row.get("summary") or "")


@router.post("/tasks/agents/chat/send", include_in_schema=False)
async def agent_chat_send(message: str = Form(...),
                          user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    body = (message or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="empty message")
    s = store.get_session(user.email)
    await _hydrate(user.email, s)
    if s.streaming:
        # Kept, not refused. The round in flight drains this when it finishes,
        # so there is still only ever one round, and no stream block is
        # returned: a second EventSource would claim a round of its own and
        # run two at once, which is what the single-round guard exists to
        # prevent.
        s.queued.append(body)
        return HTMLResponse(render.user_bubble(body))

    s.messages.append({"role": "user", "content": body})
    s.streaming = True
    # First message ever: write the row now rather than at the end of the
    # round, so a browser that closes mid-answer still has the question.
    # Best effort, because a database problem must not cost somebody their
    # turn; the conversation simply stays unsaved.
    if s.chat_id is None:
        try:
            s.chat_id = await store.create_chat(
                user.email, store.title_from(body), s)
        except Exception:                                   # noqa: BLE001
            log.exception("agent chat: could not create the conversation row; "
                          "continuing unsaved")

    resp = HTMLResponse(render.user_bubble(body) + render.stream_block())
    resp.headers["HX-Trigger"] = "agent-chats-changed"
    return resp


@router.get("/tasks/agents/chat/stream", include_in_schema=False)
async def agent_chat_stream(request: Request,
                            user: CurrentUser = Depends(current_user)
                            ) -> EventSourceResponse:
    s = store.get_session(user.email)

    async def gen():
        # Only ever answer an unanswered message. A browser reconnects an
        # EventSource by itself, and without this the reconnect re-runs the
        # whole round: an infinite loop that costs real money.
        if not s.messages or s.messages[-1].get("role") != "user":
            # Do NOT clear s.streaming here. A reconnect can reach this branch
            # while the owning round is still running, and clearing it would
            # drop the double-submit guard mid-turn.
            yield {"event": "close", "data": ""}
            return

        # Claim the round before the first await, by flipping the tail off
        # "user". Anything reconnecting from here on fails the check above.
        my_generation = s.generation
        claim = {"role": "round", "content": ""}
        s.messages.append(claim)
        try:
            agents = await _agents_for(user.email)
            while True:
                # Before the round, so the agents answering this message are
                # the ones reading the notes.
                await _keep_within_budget(user.email, s, agents)
                async for event in _run_round(user.email, s, agents, request):
                    yield event

                # Anything typed while that was running gets answered now, on
                # this same connection. One round at a time still holds; the
                # queue only changes whether a message waits or is refused.
                if s.generation != my_generation:
                    break
                if request is not None and await request.is_disconnected():
                    break
                nxt = _take_queued(s)
                if nxt is None:
                    break
                # The claim moves to the top again. Between rounds the tail is
                # an assistant message, and appending a user message would put
                # "user" back on the tail, which is exactly the shape a
                # reconnecting EventSource reads as "nobody has answered this
                # yet" and would run a second round for.
                _drop(s.messages, claim)
                s.messages.append({"role": "user", "content": nxt})
                s.messages.append(claim)
                # No bubble is emitted: the send that queued this already
                # returned one and the browser has drawn it.
        finally:
            still_ours = (s.generation == my_generation
                          and any(m is claim for m in s.messages))
            if still_ours:
                # An answer now holds the tail, so the bookkeeping marker has
                # done its job. If nothing answered, it stays: the tail must
                # not fall back to "user" or a reconnect re-runs the round.
                if s.messages[-1] is not claim:
                    _drop(s.messages, claim)
                try:
                    await store.save_chat(user.email, s)
                except Exception:                           # noqa: BLE001
                    log.exception("agent chat: could not save conversation %s",
                                  s.chat_id)
            # Only clear the flag if this round still owns this generation.
            # New chat can bump s.generation and let a fresh send re-claim
            # streaming while this round is still unwinding; clearing it
            # unconditionally would drop that newer claim's double-submit
            # guard and let a third send run a round concurrently with it.
            if s.generation == my_generation:
                s.streaming = False
            yield {"event": "close", "data": ""}

    return EventSourceResponse(gen())


@router.post("/tasks/agents/chat/approve", include_in_schema=False)
async def agent_chat_approve(ask_id: str = Form(...),
                             approved: str = Form(...),
                             user: CurrentUser = Depends(current_user)
                             ) -> HTMLResponse:
    """Answer one agent's request to run a tool.

    Addressed by the question, not by the agent, because one agent can have
    two questions outstanding. The question lives in the asker's own session,
    so there is nothing a stranger can address. The held conversation goes
    from here straight into _resume_turn without ever having been in a
    browser.
    """
    s = store.get_session(user.email)
    # Looked up, not popped: a stranger's click or a click mid round must not
    # discard the real owner's still-pending question, so nothing is taken
    # off the session until both of those are ruled out.
    pending = s.pending.get(ask_id)
    if not isinstance(pending, dict) or not pending.get("calls"):
        return HTMLResponse(render.note(
            "That question is no longer waiting for an answer."))
    # Belt and braces, checked before anything is popped. The payload names
    # who was asked; the session is already per person, so these can only
    # disagree if something upstream changed.
    if pending.get("user_email") and pending["user_email"] != user.email:
        log.warning("agent chat: refused an approval from the wrong person")
        return HTMLResponse(render.note(
            "That question is no longer waiting for an answer."))

    # Which agent asked is still needed: to name the speaker, and to resume
    # the right one. It is read off the held payload rather than taken from
    # the form, so a browser cannot point an answer at a different agent.
    agent_id = str(pending.get("agent_id") or "")
    agents = await _agents_for(user.email)
    name = _name_for(agent_id, agents) or "Agent"

    if s.streaming:
        # Another agent in this round is still running. Agents run one at a
        # time, never in parallel: a turn can run tools and this box has
        # 3.8GB of RAM. Leave the question in place and hand back the same
        # buttons rather than a bare note, or hx-swap would replace them and
        # the person could never answer once the round finished.
        busy = render.note("The others are still answering. Try again in a "
                           "moment.")
        page_pending = _pending_for_page(pending)
        if not page_pending:
            return HTMLResponse(busy)
        return HTMLResponse(
            busy + render.approval_bubble(name, ask_id,
                                          page_pending["calls"]))

    s.pending.pop(ask_id, None)
    # Cleared here, before the resume runs, so a reload shows no stale Yes
    # and No whatever _resume_turn does next.
    _clear_awaiting(s.messages, ask_id)

    yes = (approved or "").strip().lower() in ("yes", "true", "1", "on")
    try:
        out = await _resume_turn(
            user_email=user.email, agent_id=agent_id,
            conversation=list(pending.get("conversation") or []),
            calls=list(pending.get("calls") or []), approved=yes)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: resume failed for %s", agent_id)
        try:
            await store.save_chat(user.email, s)
        except Exception:                                   # noqa: BLE001
            log.exception("agent chat: could not save after a failed "
                          "approval")
        # The pending stays popped. On a timeout the tool may already have
        # run, so putting the question back and offering Yes again could run
        # it a second time. Failing closed here is deliberate, not a bug.
        return HTMLResponse(render.note(
            "That could not be completed, so it is no longer waiting for "
            "an answer."))
    answer = out.get("answer") or ""

    raw_pending = out.get("pending")
    page_pending = (_pending_for_page(raw_pending)
                    if isinstance(raw_pending, dict) else None)
    if page_pending:
        # It asked again. Same rules, and a new question, so a new id: the
        # one just answered is spent.
        next_ask = _ask_id()
        s.pending[next_ask] = raw_pending
        awaiting = dict(page_pending)
        awaiting["ask_id"] = next_ask
        s.messages.append({"role": "assistant", "agent_id": agent_id,
                           "agent_name": name, "content": answer,
                           "awaiting": awaiting})
        html = ((render.agent_bubble(name, answer) if answer else "")
                + render.approval_bubble(name, next_ask,
                                         page_pending["calls"]))
    else:
        s.messages.append({"role": "assistant", "agent_id": agent_id,
                           "agent_name": name, "content": answer})
        html = render.agent_bubble(name, answer)

    try:
        await store.save_chat(user.email, s)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not save after an approval")
    return HTMLResponse(html)


@router.get("/tasks/agents/chat/thread", include_in_schema=False)
async def agent_chat_thread(user: CurrentUser = Depends(current_user)
                            ) -> HTMLResponse:
    """The conversation so far.

    The panel asks for this on load. There is one room and it is permanent,
    so opening the page mid-conversation should show the conversation.
    """
    s = store.get_session(user.email)
    await _hydrate(user.email, s)
    return HTMLResponse(render.thread(s.messages))


@router.post("/tasks/agents/chat/clear", include_in_schema=False)
async def agent_chat_clear(user: CurrentUser = Depends(current_user)
                           ) -> HTMLResponse:
    """Empty the room and start again.

    The row is kept and emptied rather than deleted, so there stays exactly
    one conversation per person and nothing has to decide which of two is
    the real one.
    """
    s = store.get_session(user.email)
    await _hydrate(user.email, s)
    # Replaced, never cleared in place: a round still running holds these
    # objects and must keep writing into the ones it started with rather
    # than into the fresh conversation.
    s.messages = []
    s.pending = {}
    # Emptied with everything else. A message typed into the conversation that
    # was just cleared must not be answered inside the new one.
    s.queued = []
    s.summary = ""
    s.summarised_upto = 0
    s.streaming = False
    # Invalidate any round still running against what was just emptied.
    s.generation += 1
    if s.chat_id:
        try:
            await store.save_chat(user.email, s)
        except Exception:                                   # noqa: BLE001
            log.exception("agent chat: could not save after clearing")
    return HTMLResponse(render.empty_thread())
