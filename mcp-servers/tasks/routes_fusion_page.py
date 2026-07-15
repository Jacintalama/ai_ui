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

_DEFAULT_PANEL, _DEFAULT_JUDGE = fusion_engine.resolve_preset("quality")

_SESSION_IDLE_SECONDS = 2 * 60 * 60  # drop sessions idle longer than 2h


@dataclass
class FusionSession:
    messages: list[dict] = field(default_factory=list)
    panel: list[str] = field(default_factory=lambda: list(_DEFAULT_PANEL))
    judge: str = _DEFAULT_JUDGE
    preset_label: str = "quality"
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


def _render_picker(s: FusionSession) -> str:
    """The model-picker fragment: preset tabs, panel chips (with remove), an
    Add-model button that opens a modal, and a judge select. Server-rendered;
    every mutation returns this whole fragment (hx-swap outerHTML into #picker)."""
    models = fusion_engine.available_models()
    label_by_id = {m["id"]: m["label"] for m in models}
    prov_by_id = {m["id"]: m["provider"] for m in models}
    prov_name = {"openai": "OpenAI", "anthropic": "Anthropic"}

    # Preset tabs. Quality/Budget switch the selection; Custom is a passive
    # indicator that lights up when the selection was hand-edited.
    tabs = []
    for name in ("quality", "budget"):
        active = " active" if s.preset_label == name else ""
        tabs.append(
            f'<button class="tab{active}" hx-post="/tasks/fusion/preset" '
            f'hx-vals=\'{{"name": "{name}"}}\' hx-target="#picker" '
            f'hx-swap="outerHTML">{name.capitalize()}</button>')
    custom_active = " active" if s.preset_label == "custom" else ""
    tabs.append(f'<span class="tab passive{custom_active}">Custom</span>')

    # Panel chips (each with a provider dot). The remove button is omitted when
    # only one chip remains.
    chips = []
    can_remove = len(s.panel) > 1
    for mid in s.panel:
        lbl = _esc(label_by_id.get(mid, mid))
        dot = _esc(prov_by_id.get(mid, ""))
        remove = ""
        if can_remove:
            remove = (f'<button class="x" hx-post="/tasks/fusion/panel/remove" '
                      f'hx-vals=\'{{"model": "{_esc(mid)}"}}\' hx-target="#picker" '
                      f'hx-swap="outerHTML" title="remove">&times;</button>')
        chips.append(
            f'<span class="chip"><span class="dot {dot}"></span>{lbl}{remove}</span>')

    # Add-model button + modal (only when there is room; both omitted at 4).
    add_btn = ""
    modal = ""
    if len(s.panel) < 4:
        add_btn = ('<button type="button" class="addbtn" '
                   'onclick="openAddModal()">+ Add model</button>')
        rows = []
        for m in models:
            if m["id"] in s.panel:
                continue
            pn = _esc(prov_name.get(m["provider"], m["provider"]))
            rows.append(
                f'<button type="button" class="mrow" '
                f'data-name="{_esc(m["label"].lower())}" '
                f'hx-post="/tasks/fusion/panel/add" '
                f'hx-vals=\'{{"model": "{_esc(m["id"])}"}}\' '
                f'hx-target="#picker" hx-swap="outerHTML">'
                f'<span class="dot {_esc(m["provider"])}"></span>'
                f'<span class="mname">{_esc(m["label"])}</span>'
                f'<span class="mprov">{pn}</span></button>')
        modal = (
            '<div class="modal-backdrop" id="addModal" '
            'onclick="if(event.target===this)closeAddModal()">'
            '<div class="modal">'
            '<div class="modal-head"><span>Add a model</span>'
            '<button type="button" class="mx" onclick="closeAddModal()" '
            'aria-label="close">&times;</button></div>'
            '<input class="msearch" type="text" placeholder="Search models" '
            'oninput="filterModels(this.value)" autocomplete="off" />'
            f'<div class="mlist">{"".join(rows)}</div>'
            '</div></div>')

    # Judge select (all models; current judge selected).
    jopts = []
    for m in models:
        sel = " selected" if m["id"] == s.judge else ""
        jopts.append(f'<option value="{_esc(m["id"])}"{sel}>{_esc(m["label"])}</option>')
    judge = ('<select class="judge" hx-post="/tasks/fusion/judge" '
             'hx-trigger="change" hx-target="#picker" hx-swap="outerHTML" '
             'name="model">' + "".join(jopts) + '</select>')

    return (
        '<div id="picker" class="picker">'
        f'<div class="tabs">{"".join(tabs)}</div>'
        f'<div class="row"><span class="rlabel">Panel</span>{"".join(chips)}{add_btn}</div>'
        f'<div class="row"><span class="rlabel">Fuse with</span>{judge}</div>'
        f'{modal}'
        '</div>'
    )


@router.get("/tasks/fusion", include_in_schema=False)
async def fusion_page() -> FileResponse:
    return FileResponse("static/fusion.html", media_type="text/html")


@router.post("/tasks/fusion/send", include_in_schema=False)
async def fusion_send(message: str = Form(...),
                      user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty message")
    s = _get_session(user.email)
    if not s.panel:
        raise HTTPException(status_code=400, detail="pick at least one model")
    if s.streaming:
        return HTMLResponse(
            '<div class="msg system">Still answering the previous turn, '
            'one moment.</div>')
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
            # Do NOT clear s.streaming here: a concurrent reconnect can hit this
            # branch while the owning generator is still fusing, and clearing it
            # would drop the double-submit guard mid-turn. The owning gen's
            # finally is the only place that resets streaming.
            yield {"event": "close", "data": ""}
            return
        # Claim the turn atomically, before the first `await`. Appending the
        # assistant placeholder flips messages[-1] to "assistant", so any
        # concurrent or reconnecting stream for this same session fails the
        # pending-turn check above and closes without a second paid fan-out.
        # `fuse` runs against a snapshot so a New chat mid-stream cannot mutate
        # the list it is reading. The snapshot drops any empty-content turn (an
        # assistant placeholder left by an earlier early-disconnect): empty
        # content is rejected by the Anthropic API and would silently drop every
        # Claude panelist for the rest of the conversation.
        my_generation = s.generation
        fuse_messages = [m for m in s.messages if (m.get("content") or "").strip()]
        placeholder = {"role": "assistant", "content": ""}
        s.messages.append(placeholder)
        collected: list[str] = []
        try:
            async for chunk in fusion_engine.fuse(fuse_messages, s.panel, s.judge):
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


@router.get("/tasks/fusion/picker", include_in_schema=False)
async def fusion_picker(
        user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    return HTMLResponse(_render_picker(_get_session(user.email)))


@router.post("/tasks/fusion/preset", include_in_schema=False)
async def fusion_preset(name: str = Form(...),
                        user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if name not in fusion_engine.PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown preset: {name}")
    s = _get_session(user.email)
    s.panel, s.judge = fusion_engine.resolve_preset(name)
    s.preset_label = name
    return HTMLResponse(_render_picker(s))


@router.post("/tasks/fusion/panel/add", include_in_schema=False)
async def fusion_panel_add(model: str = Form(...),
                           user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if model not in fusion_engine.PROVIDER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown model: {model}")
    s = _get_session(user.email)
    if model not in s.panel and len(s.panel) < 4:
        s.panel.append(model)
        s.preset_label = "custom"
    return HTMLResponse(_render_picker(s))


@router.post("/tasks/fusion/panel/remove", include_in_schema=False)
async def fusion_panel_remove(model: str = Form(...),
                              user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    s = _get_session(user.email)
    if model in s.panel and len(s.panel) > 1:
        s.panel.remove(model)
        s.preset_label = "custom"
    return HTMLResponse(_render_picker(s))


@router.post("/tasks/fusion/judge", include_in_schema=False)
async def fusion_judge(model: str = Form(...),
                       user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if model not in fusion_engine.PROVIDER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown model: {model}")
    s = _get_session(user.email)
    s.judge = model
    s.preset_label = "custom"
    return HTMLResponse(_render_picker(s))
