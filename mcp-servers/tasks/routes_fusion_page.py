"""Fusion chat page: a dedicated in-tasks-service page where a signed-in user
chats with Model Fusion (a model panel plus a judge) and gets one synthesized
answer per turn. Server-rendered HTML plus vendored HTMX. Per-user in-memory
session, no persistence (cleared on restart or New chat). Reuses fusion_engine
in-process, so there is no internal HTTP hop.

All routes live under the /tasks prefix, which is already routed to this
service end to end, so no gateway or proxy change is needed."""
import html
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sse_starlette.sse import EventSourceResponse

import fusion_engine
from auth import CurrentUser, current_user

router = APIRouter()

_SESSION_IDLE_SECONDS = 2 * 60 * 60  # drop sessions idle longer than 2h


@dataclass
class FusionSession:
    messages: list[dict] = field(default_factory=list)
    preset: str = "quality"
    streaming: bool = False
    last_used: float = field(default_factory=time.time)
    # Bumped whenever the session is reset (New chat). A stream generator
    # captures it at start and refuses to write its result back if the value
    # changed underneath it, so an in-flight turn can never corrupt a session
    # the user has since cleared or restarted.
    generation: int = 0


_SESSIONS: dict[str, FusionSession] = {}


def _sweep(now: float | None = None) -> None:
    """Drop sessions idle longer than the TTL. Called lazily on access."""
    now = time.time() if now is None else now
    stale = [k for k, s in _SESSIONS.items()
             if now - s.last_used > _SESSION_IDLE_SECONDS]
    for k in stale:
        del _SESSIONS[k]


def _get_session(email: str) -> FusionSession:
    _sweep()
    s = _SESSIONS.get(email)
    if s is None:
        s = FusionSession()
        _SESSIONS[email] = s
    s.last_used = time.time()
    return s


def _esc(text: str) -> str:
    return html.escape(text or "")


def _user_bubble(text: str) -> str:
    return f'<div class="msg user"><div class="bubble">{_esc(text)}</div></div>'


def _assistant_bubble_streaming() -> str:
    """An assistant bubble that opens an SSE connection to the stream route.
    Tokens arrive as "message" events and are appended (hx-swap=beforeend). The
    terminal "close" event closes the stream (sse-close) so the browser's
    EventSource does not auto-reconnect and re-run the fusion."""
    return (
        '<div class="msg assistant">'
        '<div class="bubble" hx-ext="sse" sse-connect="/tasks/fusion/stream" '
        'sse-swap="message" hx-swap="beforeend" sse-close="close"></div>'
        '</div>'
    )


def _empty_thread() -> str:
    return ('<div class="empty">Ask a panel of models. '
            'You get one synthesized answer.</div>')


@router.get("/tasks/fusion", include_in_schema=False)
async def fusion_page() -> FileResponse:
    return FileResponse("static/fusion.html", media_type="text/html")


@router.post("/tasks/fusion/send", include_in_schema=False)
async def fusion_send(message: str = Form(...), preset: str = Form("quality"),
                      user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if preset not in fusion_engine.PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown preset: {preset}")
    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty message")
    s = _get_session(user.email)
    if s.streaming:
        return HTMLResponse(
            '<div class="msg system">Still answering the previous turn, '
            'one moment.</div>')
    s.preset = preset
    s.messages.append({"role": "user", "content": text})
    s.streaming = True
    return HTMLResponse(_user_bubble(text) + _assistant_bubble_streaming())


@router.get("/tasks/fusion/stream", include_in_schema=False)
async def fusion_stream(request: Request,
                        user: CurrentUser = Depends(current_user)
                        ) -> EventSourceResponse:
    s = _get_session(user.email)

    async def gen():
        # Only answer when there is a pending user turn. This guards against
        # the browser EventSource auto-reconnecting and re-running the fusion
        # on an already-answered session (an infinite loop plus real cost).
        if not s.messages or s.messages[-1].get("role") != "user":
            s.streaming = False
            yield {"event": "close", "data": ""}
            return
        # Claim the turn atomically, before the first `await`. Appending the
        # assistant placeholder flips messages[-1] to "assistant", so any
        # concurrent or reconnecting stream for this same session fails the
        # pending-turn check above and closes without a second paid fan-out.
        # `fuse` runs against a snapshot so a New chat mid-stream cannot mutate
        # the list it is reading.
        my_generation = s.generation
        fuse_messages = list(s.messages)
        placeholder = {"role": "assistant", "content": ""}
        s.messages.append(placeholder)
        collected: list[str] = []
        try:
            async for chunk in fusion_engine.fuse(fuse_messages, s.preset):
                if not chunk:
                    continue
                if await request.is_disconnected():
                    break
                collected.append(chunk)
                yield {"event": "message", "data": _esc(chunk)}
        finally:
            full = "".join(collected)
            # Resolve the claimed turn to its answer, but only if this session
            # was not reset (New chat) and our placeholder is still present.
            # Otherwise the turn was abandoned and its result must be discarded,
            # not stapled onto a newer conversation. We always fill the
            # placeholder (even with "" on an early disconnect) rather than
            # removing it, so the turn is never left pending: a later reconnect
            # then closes without a second, already-paid fan-out.
            if s.generation == my_generation and placeholder in s.messages:
                placeholder["content"] = full
            s.streaming = False
            yield {"event": "close", "data": ""}

    return EventSourceResponse(gen())


@router.post("/tasks/fusion/new", include_in_schema=False)
async def fusion_new(
        user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    s = _get_session(user.email)
    s.messages.clear()
    s.streaming = False
    # Invalidate any stream still running against the old conversation so its
    # result is discarded instead of being appended to the fresh session.
    s.generation += 1
    return HTMLResponse(_empty_thread())
