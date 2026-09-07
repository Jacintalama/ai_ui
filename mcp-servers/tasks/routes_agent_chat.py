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
from routes_agent_turn import _agents_for, _resume_turn, _turn_for
from routes_agents import _pending_for_page

log = logging.getLogger(__name__)

router = APIRouter()

#: Agents run one at a time, so a room is a queue. Four is already a slow round.
MAX_ROOM = 4

#: How many messages of the conversation a round hands each agent.
#: A room of four adds four assistant messages for every one you send, and
#: every agent in the next round is billed for all of them, so an afternoon's
#: conversation quietly costs several times itself on a 3.8GB box. Recent
#: turns are what an answer needs; the rest is paid for and unread.
MAX_HISTORY_MESSAGES = 20


def _ask_id() -> str:
    """A name for one question an agent asked.

    Not the agent's id. The same agent can be waiting on two answers at once
    if a second message goes out while the first question is unanswered, and
    keying on the agent would have the second overwrite the first: a held
    conversation discarded without anybody being told, and two Yes buttons on
    the page pointing at the same element.
    """
    return uuid.uuid4().hex


def _history_for_round(messages: list[dict]) -> list[dict]:
    """The conversation every agent in this round sees. Built ONCE.

    Role and content only: agent_id and agent_name are ours, for drawing the
    bubbles, and mean nothing to a model. Empty turns are dropped because empty
    content is rejected upstream. Bookkeeping roles fall out here too.

    Capped at MAX_HISTORY_MESSAGES, oldest dropped first, because otherwise a
    long conversation is re-sent in full to every agent in the room on every
    message you send.
    """
    out = []
    for m in messages or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    first = max(0, len(out) - MAX_HISTORY_MESSAGES)
    # The message being answered is the whole point of the round, so the
    # window widens to reach it rather than ever cutting it off.
    newest_user = max((i for i, m in enumerate(out) if m["role"] == "user"),
                      default=None)
    if newest_user is not None:
        first = min(first, newest_user)
    return out[first:]


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


def _skipped_line(count: int) -> str:
    """One sentence for however many of the room could not be found."""
    if count == 1:
        return ("An agent that was in this room no longer exists, "
                "so it was skipped.")
    return (f"{count} agents that were in this room no longer exist, "
            "so they were skipped.")


def _name_for(agent_id: str, agents: list[dict]) -> str:
    for a in agents:
        if str(a.get("id")) == agent_id:
            return str(a.get("name") or agent_id)
    return agent_id


async def _run_round(email: str, s: store.RoomSession, agents: list[dict],
                     request: Request | None = None):
    """Yield one SSE event per thing that happens in a round.

    Agents run one at a time, never in parallel: a turn can run tools and this
    box has 3.8GB of RAM.
    """
    by_id = {str(a.get("id")): a for a in agents}
    names = [a.get("name") for a in agents if a.get("name")]
    # Built once, before the first agent runs, and handed unchanged to every
    # agent. See the module docstring of routes_agent_turn for what happens
    # when agents read each other's labelled replies.
    history = _history_for_round(s.messages)
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

    # Counted, not announced one by one. _agents_for returns nothing on any
    # doubt, a listing cut short included, so an upstream hiccup used to put
    # the same sentence in the thread once per seated agent and no answers at
    # all. The spec asks for it once.
    skipped = 0

    for agent_id in list(s.room):
        if request is not None and await request.is_disconnected():
            break
        agent = by_id.get(agent_id)
        if agent is None:
            skipped += 1
            continue

        name = str(agent.get("name") or agent_id)
        yield {"event": "working", "data": render.working(name)}
        out = await _turn_for(email, agent, history, names)
        answer = out.get("answer") or ""

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

    if skipped:
        line = _skipped_line(skipped)
        messages.append({"role": "note", "content": line})
        yield {"event": "message", "data": render.note(line)}

    yield {"event": "working", "data": ""}


@router.post("/tasks/agents/chat/send", include_in_schema=False)
async def agent_chat_send(message: str = Form(...),
                          user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    body = (message or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="empty message")
    s = store.get_session(user.email)
    if not s.room:
        return HTMLResponse(render.note(
            "Pick at least one agent first, then ask again."))
    if s.streaming:
        return HTMLResponse(render.note(
            "Still answering, one moment. If it ever stays stuck, New chat "
            "starts a fresh one."))

    s.messages.append({"role": "user", "content": body})
    s.streaming = True
    # First message of an unsaved conversation: write the row now so it appears
    # in the list immediately. Best effort, because a database problem must not
    # cost somebody their turn; the conversation simply stays unsaved.
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
            async for event in _run_round(user.email, s, agents, request):
                yield event
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


@router.get("/tasks/agents/chat/room", include_in_schema=False)
async def agent_chat_room(user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    s = store.get_session(user.email)
    return HTMLResponse(render.chips(await _agents_for(user.email), s.room))


@router.post("/tasks/agents/chat/room/add", include_in_schema=False)
async def agent_chat_room_add(agent_id: str = Form(...),
                              user: CurrentUser = Depends(current_user)
                              ) -> HTMLResponse:
    s = store.get_session(user.email)
    agents = await _agents_for(user.email)
    # Only your own agents, checked here rather than trusted from the form.
    # Seating a stranger's agent would run it as you.
    known = {str(a.get("id")) for a in agents}
    if agent_id in known and agent_id not in s.room and len(s.room) < MAX_ROOM:
        s.room.append(agent_id)
    return HTMLResponse(render.chips(agents, s.room))


@router.post("/tasks/agents/chat/room/remove", include_in_schema=False)
async def agent_chat_room_remove(agent_id: str = Form(...),
                                 user: CurrentUser = Depends(current_user)
                                 ) -> HTMLResponse:
    s = store.get_session(user.email)
    if agent_id in s.room:
        s.room.remove(agent_id)
    return HTMLResponse(render.chips(await _agents_for(user.email), s.room))


@router.post("/tasks/agents/chat/new", include_in_schema=False)
async def agent_chat_new(user: CurrentUser = Depends(current_user)
                         ) -> HTMLResponse:
    s = store.get_session(user.email)
    # Replaced, not cleared in place. A round still running when New chat is
    # clicked keeps the object it was bound to in _run_round; a fresh list
    # and dict here detach that round from this session instead of it
    # continuing to append into the conversation being started now.
    s.messages = []
    s.pending = {}
    s.streaming = False
    # Detach from the saved row. It stays; this session just stops being about
    # it, so the next message starts a new conversation rather than appending
    # to the one that was walked away from.
    s.chat_id = None
    # Invalidate any round still running against the old conversation, so its
    # result is discarded instead of landing in the fresh one.
    s.generation += 1
    # The room is deliberately kept: picking the same people again every time
    # would be the main annoyance of a panel like this.
    resp = HTMLResponse(render.empty_thread())
    resp.headers["HX-Trigger"] = "agent-chats-changed"
    return resp


@router.get("/tasks/agents/chat/chats", include_in_schema=False)
async def agent_chat_chats(user: CurrentUser = Depends(current_user)
                           ) -> HTMLResponse:
    s = store.get_session(user.email)
    try:
        chats = await store.list_chats(user.email)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not list conversations for %s",
                      user.email)
        chats = []
    return HTMLResponse(render.chat_list(chats, s.chat_id))


@router.get("/tasks/agents/chat/chat/{chat_id}", include_in_schema=False)
async def agent_chat_open(chat_id: str,
                          user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    try:
        row = await store.load_chat(user.email, chat_id)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not load conversation %s", chat_id)
        # Session left untouched: a database hiccup must not knock somebody
        # out of the conversation they were already in.
        return HTMLResponse(render.note(
            "That conversation could not be opened just now."))
    if row is None:
        raise HTTPException(status_code=404, detail="no such conversation")
    s = store.get_session(user.email)
    s.messages = list(row.get("messages") or [])
    s.room = list(row.get("room") or [])
    s.pending = dict(row.get("pending") or {})
    s.chat_id = str(row["id"])
    s.streaming = False
    # Anything still running against the previous conversation is now orphaned.
    s.generation += 1
    resp = HTMLResponse(render.thread(s.messages))
    resp.headers["HX-Trigger"] = "agent-chats-changed"
    return resp


@router.delete("/tasks/agents/chat/chat/{chat_id}", include_in_schema=False)
async def agent_chat_delete(chat_id: str,
                            user: CurrentUser = Depends(current_user)
                            ) -> HTMLResponse:
    try:
        await store.delete_chat(user.email, chat_id)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not delete conversation %s", chat_id)
        # Session left untouched too: if the delete raised, the row is still
        # there, so nothing about what this session has open should change.
        return HTMLResponse(render.note(
            "That conversation could not be deleted just now."))
    s = store.get_session(user.email)
    if s.chat_id == chat_id:
        # Replaced, not cleared in place. See _run_round and agent_chat_new
        # for why: a round still running against this conversation keeps the
        # object it was bound to, and a fresh list and dict here detach it
        # instead of it continuing to append into a conversation that no
        # longer exists.
        s.messages = []
        s.pending = {}
        s.chat_id = None
        s.streaming = False
        s.generation += 1
    try:
        chats = await store.list_chats(user.email)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not list conversations for %s",
                      user.email)
        chats = []
    return HTMLResponse(render.chat_list(chats, s.chat_id))
