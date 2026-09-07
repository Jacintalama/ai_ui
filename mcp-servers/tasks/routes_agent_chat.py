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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

import agent_chat_render as render
import agent_chat_store as store
from auth import CurrentUser, current_user
from routes_agent_turn import _agents_for, _turn_for
from routes_agents import _pending_for_page

log = logging.getLogger(__name__)

router = APIRouter()

#: Agents run one at a time, so a room is a queue. Four is already a slow round.
MAX_ROOM = 4


def _history_for_round(messages: list[dict]) -> list[dict]:
    """The conversation every agent in this round sees. Built ONCE.

    Role and content only: agent_id and agent_name are ours, for drawing the
    bubbles, and mean nothing to a model. Empty turns are dropped because empty
    content is rejected upstream. Bookkeeping roles fall out here too.
    """
    out = []
    for m in messages or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def _drop(messages: list[dict], marker: dict) -> None:
    """Remove `marker` by identity.

    Not list.remove, which matches by equality: two empty bookkeeping dicts
    compare equal, so remove() can delete the wrong one.
    """
    for i, m in enumerate(messages):
        if m is marker:
            del messages[i]
            return


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

    for agent_id in list(s.room):
        if request is not None and await request.is_disconnected():
            break
        agent = by_id.get(agent_id)
        if agent is None:
            line = ("An agent that was in this room no longer exists, "
                    "so it was skipped.")
            s.messages.append({"role": "note", "content": line})
            yield {"event": "message", "data": render.note(line)}
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
            s.pending[agent_id] = raw_pending
            s.messages.append({"role": "assistant", "agent_id": agent_id,
                               "agent_name": name, "content": answer,
                               "awaiting": page_pending})
            if answer:
                yield {"event": "message",
                       "data": render.agent_bubble(name, answer)}
            yield {"event": "message",
                   "data": render.approval_bubble(name, agent_id,
                                                  page_pending["calls"])}
            # And on to the next agent. Pausing the one that asked is the
            # point; silently losing everybody else is not.
            continue

        s.messages.append({"role": "assistant", "agent_id": agent_id,
                           "agent_name": name, "content": answer})
        yield {"event": "message", "data": render.agent_bubble(name, answer)}

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
        return HTMLResponse(render.note("Still answering, one moment."))

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
            s.streaming = False
            yield {"event": "close", "data": ""}

    return EventSourceResponse(gen())
