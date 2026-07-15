# Fusion Chat Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Model Fusion its own dedicated in-app chat page (a "Fusion" sidebar entry) served by the FastAPI tasks-service, replacing the Open WebUI dropdown-pipe access.

**Architecture:** A new `routes_fusion_page.py` in the tasks-service serves a server-rendered HTML page (`static/fusion.html`) wired with vendored HTMX. The composer POSTs to `/tasks/fusion/send`, which appends to a per-user in-memory session and returns an HTML fragment whose assistant bubble opens an SSE connection to `/tasks/fusion/stream`. The stream calls `fusion_engine.fuse(...)` in-process (fan-out GPT + Claude, judge synthesizes) and relays tokens as SSE events. The old OWUI pipe, its installer, and the internal `/api/fusion` route are removed.

**Tech Stack:** Python 3.11, FastAPI, `sse_starlette.EventSourceResponse` (already a dependency), HTMX 1.9.12 + its SSE extension (vendored, served locally), pytest.

## Global Constraints

Copy these verbatim into every task; they bind all tasks.

- **Routing decision (differs from spec):** the page and all its endpoints live under the **`/tasks/`** prefix (`/tasks/fusion`, `/tasks/fusion/send`, `/tasks/fusion/stream`, `/tasks/fusion/new`). This prefix is ALREADY routed to the tasks-service end-to-end (proven live by `/tasks/app-builder`), so there is **NO** `api-gateway/main.py` change and **NO** host-Caddy change. Do not add a `/fusion` gateway block. The sidebar nav href is `/tasks/fusion`.
- **Auth model:** the page HTML (`GET /tasks/fusion`) is unauthenticated static HTML. The data endpoints (`send`, `stream`, `new`) use `Depends(current_user)` from `auth.py`, which reads the gateway-injected `X-User-Email` header (401 if missing). The gateway derives that header from EITHER an `Authorization: Bearer <token>` header OR the OWUI `token` cookie. Native `EventSource` (used by the HTMX SSE extension) cannot send an `Authorization` header, so `/tasks/fusion/stream` authenticates via the same-origin cookie. HTMX POST requests add `Authorization: Bearer <localStorage token>` via `htmx:configRequest`.
- **SSE reconnect safety (critical):** the browser's `EventSource` auto-reconnects when the server closes a stream. The stream MUST (a) emit a terminal SSE event named `close` and the assistant bubble MUST carry `sse-close="close"` so HTMX closes the connection, AND (b) the stream generator MUST run `fuse` only when the session's last message role is `"user"` (a pending turn) - otherwise a reconnect re-runs `fuse` on an already-answered session, causing an infinite loop and real API cost.
- **No em-dashes or en-dashes** anywhere (code, comments, docstrings, HTML copy, commit messages). Use `-`, a comma, or "and"/"so". This includes generated fragments.
- **No AI/Claude attribution** in commit messages, PR bodies, or code comments. Commits are authored as Ralph Benitez / thunder500 only. Write the commit message and stop; do NOT append `Co-Authored-By` or `Generated with` lines.
- **Never touch or commit `.env`**, and never deploy `mcp-servers/tasks/templates.py`.
- **Reuse `fusion_engine.py` unchanged.** Do not modify the engine, its registry, or its presets. The valid presets are exactly the keys of `fusion_engine.PRESETS` (`"quality"`, `"budget"`).
- **Working directory for tests:** the tasks-service test suite runs from `mcp-servers/tasks/` (imports are bare, e.g. `import fusion_engine`, `from auth import current_user`). Place tests in `mcp-servers/tasks/tests/` and run pytest from `mcp-servers/tasks/`.
- **Python style:** type hints on new function signatures, `async`/`await` for I/O, no `print()` (use nothing or `logging`), 3.8GB-RAM-aware (the session store is tiny; do not add heavyweight deps).

---

## File Structure

- **Create** `mcp-servers/tasks/routes_fusion_page.py` - session store, HTML-fragment builders, and the four page routes (`GET /tasks/fusion`, `POST /tasks/fusion/send`, `GET /tasks/fusion/stream`, `POST /tasks/fusion/new`).
- **Create** `mcp-servers/tasks/static/fusion.html` - the single self-contained page.
- **Create** `mcp-servers/tasks/static/vendor/htmx.min.js` - vendored HTMX 1.9.12 (downloaded).
- **Create** `mcp-servers/tasks/static/vendor/sse.js` - vendored HTMX SSE extension (downloaded).
- **Create** `mcp-servers/tasks/tests/test_routes_fusion_page.py` - pytest for the routes + session store.
- **Modify** `mcp-servers/tasks/main.py` - import and register the new router (Task 1); remove the old `routes_fusion` import + `include_router` (Task 5).
- **Modify** `mcp-servers/tasks/static/task-panel.js` - add the Fusion nav entry (Task 4).
- **Delete** `open-webui-functions/fusion_pipe.py`, `scripts/install_fusion_pipe.py`, `mcp-servers/tasks/routes_fusion.py`, `mcp-servers/tasks/tests/test_routes_fusion.py` (Task 5).

---

## Task 1: Session store, fragment builders, and page/send/new routes

**Files:**
- Create: `mcp-servers/tasks/routes_fusion_page.py`
- Modify: `mcp-servers/tasks/main.py` (add import near line 16 and `include_router` near line 110)
- Test: `mcp-servers/tasks/tests/test_routes_fusion_page.py`

**Interfaces:**
- Consumes: `fusion_engine.PRESETS` (dict, keys `"quality"`/`"budget"`); `auth.current_user` (FastAPI dep returning `CurrentUser(email, is_admin)`; raises 401 when `X-User-Email` header is absent).
- Produces (Task 2 relies on these exact names): module-level `_SESSIONS: dict[str, FusionSession]`; `FusionSession` dataclass with fields `messages: list[dict]`, `preset: str`, `streaming: bool`, `last_used: float`; `_get_session(email: str) -> FusionSession`; `_sweep(now: float | None = None) -> None`; `_esc(text: str) -> str`; `_user_bubble(text: str) -> str`; `_assistant_bubble_streaming() -> str`; `_empty_thread() -> str`; `router = APIRouter()`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_routes_fusion_page.py`:

```python
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(monkeypatch):
    import importlib
    import routes_fusion_page
    importlib.reload(routes_fusion_page)
    app = FastAPI()
    app.include_router(routes_fusion_page.router)
    return app, routes_fusion_page


def _hdr(email="user@example.com"):
    return {"X-User-Email": email}


def test_send_requires_identity(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "hi", "preset": "quality"})
    assert r.status_code == 401


def test_send_unknown_preset_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "hi", "preset": "nope"},
               headers=_hdr())
    assert r.status_code == 400


def test_send_appends_user_and_returns_stream_fragment(monkeypatch):
    app, mod = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send",
               data={"message": "what is 2+2?", "preset": "budget"},
               headers=_hdr("a@b.com"))
    assert r.status_code == 200
    body = r.text
    assert 'sse-connect="/tasks/fusion/stream"' in body
    assert 'sse-close="close"' in body
    assert "what is 2+2?" in body
    sess = mod._SESSIONS["a@b.com"]
    assert sess.messages[-1] == {"role": "user", "content": "what is 2+2?"}
    assert sess.preset == "budget"
    assert sess.streaming is True


def test_send_escapes_html_in_message(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send",
               data={"message": "<script>x</script>", "preset": "quality"},
               headers=_hdr("c@d.com"))
    assert "<script>x</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_send_empty_message_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "   ", "preset": "quality"},
               headers=_hdr())
    assert r.status_code == 400


def test_send_while_streaming_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    mod._SESSIONS["e@f.com"] = mod.FusionSession(
        messages=[{"role": "user", "content": "prev"}],
        preset="quality", streaming=True, last_used=time.time())
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "again", "preset": "quality"},
               headers=_hdr("e@f.com"))
    assert r.status_code == 200
    assert "still answering" in r.text.lower()
    # the second message was NOT appended
    assert mod._SESSIONS["e@f.com"].messages == [{"role": "user", "content": "prev"}]


def test_new_clears_session(monkeypatch):
    app, mod = _app(monkeypatch)
    mod._SESSIONS["g@h.com"] = mod.FusionSession(
        messages=[{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "y"}],
        preset="quality", streaming=False, last_used=time.time())
    c = TestClient(app)
    r = c.post("/tasks/fusion/new", headers=_hdr("g@h.com"))
    assert r.status_code == 200
    assert mod._SESSIONS["g@h.com"].messages == []
    assert mod._SESSIONS["g@h.com"].streaming is False


def test_sweep_drops_idle_sessions(monkeypatch):
    _, mod = _app(monkeypatch)
    now = 1000.0
    mod._SESSIONS.clear()
    mod._SESSIONS["old@x.com"] = mod.FusionSession(last_used=now - (3 * 60 * 60))
    mod._SESSIONS["fresh@x.com"] = mod.FusionSession(last_used=now - 60)
    mod._sweep(now=now)
    assert "old@x.com" not in mod._SESSIONS
    assert "fresh@x.com" in mod._SESSIONS


def test_page_route_returns_html(monkeypatch, tmp_path):
    # The page route serves static/fusion.html; assert it is wired even before
    # the file exists by checking the route is registered (404 vs missing route).
    app, _ = _app(monkeypatch)
    routes = {r.path for r in app.routes}
    assert "/tasks/fusion" in routes
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'routes_fusion_page'`.

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/routes_fusion_page.py`:

```python
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


@router.post("/tasks/fusion/new", include_in_schema=False)
async def fusion_new(
        user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    s = _get_session(user.email)
    s.messages.clear()
    s.streaming = False
    return HTMLResponse(_empty_thread())
```

Note: the `GET /tasks/fusion/stream` route is added in Task 2. The `Request` and `EventSourceResponse` imports above are present now so Task 2 does not need to touch the import block. That is intentional, not dead code the reviewer should flag as removable this task (Task 2 uses them).

- [ ] **Step 4: Register the router in main.py**

In `mcp-servers/tasks/main.py`, add the import alongside the other `routes_*` imports (near line 16, after `from routes_fusion import router as fusion_router`):

```python
from routes_fusion_page import router as fusion_page_router
```

And add the registration alongside the other `app.include_router(...)` calls (near line 110, after `app.include_router(execution_router)`):

```python
app.include_router(fusion_page_router)  # /tasks/fusion chat page + SSE
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -v`
Expected: PASS (9 passed). If `pytest-asyncio` config warnings appear, they are pre-existing and not failures.

- [ ] **Step 6: Scan for dashes and run the full suite**

Run: `cd mcp-servers/tasks && python -m pytest -q`
Expected: the existing suite stays green plus the new tests pass.
Run: `grep -nP "[\x{2013}\x{2014}]" routes_fusion_page.py tests/test_routes_fusion_page.py`
Expected: no output (no en/em dashes).

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_fusion_page.py mcp-servers/tasks/tests/test_routes_fusion_page.py mcp-servers/tasks/main.py
git commit -m "feat(fusion): session store, fragment builders, and page/send/new routes"
```

---

## Task 2: SSE stream route wiring fusion_engine.fuse

**Files:**
- Modify: `mcp-servers/tasks/routes_fusion_page.py` (add the `GET /tasks/fusion/stream` route)
- Test: `mcp-servers/tasks/tests/test_routes_fusion_page.py` (add streaming tests)

**Interfaces:**
- Consumes: `_get_session`, `_esc`, `router`, `FusionSession`, `_SESSIONS` from Task 1; `fusion_engine.fuse(messages: list[dict], preset: str) -> AsyncIterator[str]` (async generator; never raises, degrades gracefully).
- Produces: `GET /tasks/fusion/stream` returning `EventSourceResponse`; emits `{"event": "message", "data": <html-escaped chunk>}` per token and a terminal `{"event": "close", "data": ""}`; appends `{"role": "assistant", "content": <full>}` to the session and clears `streaming` when done.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_routes_fusion_page.py`:

```python
def _seed(mod, email, messages, preset="quality", streaming=True):
    mod._SESSIONS[email] = mod.FusionSession(
        messages=list(messages), preset=preset, streaming=streaming,
        last_used=time.time())


def test_stream_relays_fuse_chunks_and_appends_assistant(monkeypatch):
    app, mod = _app(monkeypatch)

    async def fake_fuse(messages, preset, *, client=None):
        for piece in ["Final ", "answer."]:
            yield piece
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "s@t.com", [{"role": "user", "content": "q"}], streaming=True)

    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream",
                  headers=_hdr("s@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert "Final " in raw and "answer." in raw
    assert "event: close" in raw
    sess = mod._SESSIONS["s@t.com"]
    assert sess.messages[-1] == {"role": "assistant", "content": "Final answer."}
    assert sess.streaming is False


def test_stream_escapes_html_chunks(monkeypatch):
    app, mod = _app(monkeypatch)

    async def fake_fuse(messages, preset, *, client=None):
        yield "<b>hi</b>"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "esc@t.com", [{"role": "user", "content": "q"}])
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream",
                  headers=_hdr("esc@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert "<b>hi</b>" not in raw
    assert "&lt;b&gt;hi&lt;/b&gt;" in raw


def test_stream_no_pending_turn_closes_without_calling_fuse(monkeypatch):
    app, mod = _app(monkeypatch)
    called = {"fuse": False}

    async def fake_fuse(messages, preset, *, client=None):
        called["fuse"] = True
        yield "should not happen"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    # last message is assistant -> no pending user turn
    _seed(mod, "done@t.com",
          [{"role": "user", "content": "q"},
           {"role": "assistant", "content": "a"}], streaming=False)
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream",
                  headers=_hdr("done@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert called["fuse"] is False
    assert "event: close" in raw


def test_stream_requires_identity(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.get("/tasks/fusion/stream")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -k stream -v`
Expected: FAIL (route `/tasks/fusion/stream` returns 404, so assertions fail).

- [ ] **Step 3: Write the implementation**

In `mcp-servers/tasks/routes_fusion_page.py`, add this route after `fusion_send` (and before `fusion_new`):

```python
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
        collected: list[str] = []
        try:
            async for chunk in fusion_engine.fuse(s.messages, s.preset):
                if not chunk:
                    continue
                if await request.is_disconnected():
                    break
                collected.append(chunk)
                yield {"event": "message", "data": _esc(chunk)}
        finally:
            full = "".join(collected)
            if full:
                s.messages.append({"role": "assistant", "content": full})
            s.streaming = False
            yield {"event": "close", "data": ""}

    return EventSourceResponse(gen())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Scan for dashes and commit**

Run: `grep -nP "[\x{2013}\x{2014}]" routes_fusion_page.py tests/test_routes_fusion_page.py`
Expected: no output.

```bash
git add mcp-servers/tasks/routes_fusion_page.py mcp-servers/tasks/tests/test_routes_fusion_page.py
git commit -m "feat(fusion): SSE stream route relaying the fusion engine per turn"
```

---

## Task 3: The page (fusion.html) plus vendored HTMX

**Files:**
- Create: `mcp-servers/tasks/static/fusion.html`
- Create: `mcp-servers/tasks/static/vendor/htmx.min.js` (downloaded)
- Create: `mcp-servers/tasks/static/vendor/sse.js` (downloaded)

**Interfaces:**
- Consumes: `POST /tasks/fusion/send` (form fields `message`, `preset`; returns the user + assistant-stream fragment), `GET /tasks/fusion/stream` (SSE), `POST /tasks/fusion/new` (returns the empty-thread fragment). Vendored scripts are served from `/tasks/static/vendor/` (the `/tasks/static` StaticFiles mount already exists in main.py).
- Produces: the browser page; no Python interface.

- [ ] **Step 1: Download the vendored HTMX files**

Run (from repo root):

```bash
mkdir -p mcp-servers/tasks/static/vendor
curl -fsSL https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js -o mcp-servers/tasks/static/vendor/htmx.min.js
curl -fsSL https://unpkg.com/htmx.org@1.9.12/dist/ext/sse.js -o mcp-servers/tasks/static/vendor/sse.js
```

Verify both files are non-empty and look like JS:

```bash
wc -c mcp-servers/tasks/static/vendor/htmx.min.js mcp-servers/tasks/static/vendor/sse.js
head -c 80 mcp-servers/tasks/static/vendor/htmx.min.js
```

Expected: `htmx.min.js` is roughly 45-50 KB, `sse.js` a few KB; both start with JS (a comment or `(function`), not HTML. If a file is HTML or empty, the CDN failed - retry or fetch from `https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js` and `.../dist/ext/sse.js`.

- [ ] **Step 2: Write fusion.html**

Create `mcp-servers/tasks/static/fusion.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Fusion</title>
  <script src="/tasks/static/vendor/htmx.min.js"></script>
  <script src="/tasks/static/vendor/sse.js"></script>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0; height: 100vh; display: flex; flex-direction: column;
      background: #0f1115; color: #e6e8eb;
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    header {
      display: flex; align-items: center; gap: 16px;
      padding: 14px 20px; border-bottom: 1px solid #1e2230; background: #12141a;
    }
    header h1 { font-size: 16px; margin: 0; font-weight: 600; }
    .spacer { flex: 1; }
    .seg { display: inline-flex; border: 1px solid #2a2f3d; border-radius: 8px; overflow: hidden; }
    .seg label { padding: 6px 14px; cursor: pointer; font-size: 13px; color: #aeb4c0; }
    .seg input { display: none; }
    .seg input:checked + label { background: #2b6cff; color: #fff; }
    button.ghost {
      background: transparent; color: #aeb4c0; border: 1px solid #2a2f3d;
      border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 13px;
    }
    button.ghost:hover { color: #fff; border-color: #3a4152; }
    #thread {
      flex: 1; overflow-y: auto; padding: 24px 20px;
      display: flex; flex-direction: column; gap: 16px;
      max-width: 820px; width: 100%; margin: 0 auto;
    }
    .empty { color: #6b7280; text-align: center; margin: auto; }
    .msg { display: flex; }
    .msg.user { justify-content: flex-end; }
    .msg.assistant, .msg.system { justify-content: flex-start; }
    .bubble {
      max-width: 80%; padding: 10px 14px; border-radius: 12px;
      white-space: pre-wrap; word-wrap: break-word;
    }
    .msg.user .bubble { background: #2b6cff; color: #fff; }
    .msg.assistant .bubble { background: #1a1d26; border: 1px solid #262b38; }
    .msg.system .bubble, .msg.system { color: #f0b429; font-size: 13px; }
    form.composer {
      display: flex; gap: 10px; padding: 14px 20px; border-top: 1px solid #1e2230;
      background: #12141a; max-width: 820px; width: 100%; margin: 0 auto;
    }
    textarea {
      flex: 1; resize: none; height: 46px; max-height: 160px; padding: 12px 14px;
      background: #0f1115; color: #e6e8eb; border: 1px solid #2a2f3d;
      border-radius: 10px; font: inherit;
    }
    textarea:focus { outline: none; border-color: #2b6cff; }
    button.send {
      background: #2b6cff; color: #fff; border: none; border-radius: 10px;
      padding: 0 20px; cursor: pointer; font-weight: 600;
    }
    button.send:disabled { opacity: .5; cursor: default; }
  </style>
</head>
<body>
  <header>
    <h1>Fusion</h1>
    <div class="seg">
      <input type="radio" id="q" name="preset" value="quality" checked />
      <label for="q">Quality</label>
      <input type="radio" id="b" name="preset" value="budget" />
      <label for="b">Budget</label>
    </div>
    <div class="spacer"></div>
    <button class="ghost" hx-post="/tasks/fusion/new"
            hx-target="#thread" hx-swap="innerHTML">New chat</button>
  </header>

  <div id="thread">
    <div class="empty">Ask a panel of models. You get one synthesized answer.</div>
  </div>

  <form class="composer" hx-post="/tasks/fusion/send"
        hx-target="#thread" hx-swap="beforeend"
        hx-on::after-request="if(event.detail.successful){this.querySelector('textarea').value='';}">
    <input type="hidden" name="preset" id="presetField" value="quality" />
    <textarea name="message" placeholder="Ask Fusion..."
              autocomplete="off" required></textarea>
    <button class="send" type="submit">Send</button>
  </form>

  <script>
    // Keep the hidden preset field in sync with the segmented toggle.
    document.querySelectorAll('.seg input[name="preset"]').forEach(function (el) {
      el.addEventListener('change', function () {
        document.getElementById('presetField').value = el.value;
      });
    });

    // Auth: attach the OWUI login token as a Bearer header on HTMX requests.
    // The SSE stream (EventSource) cannot send headers, so it relies on the
    // same-origin OWUI cookie instead; that path needs nothing here.
    document.body.addEventListener('htmx:configRequest', function (e) {
      var token = localStorage.getItem('token');
      if (token) { e.detail.headers['Authorization'] = 'Bearer ' + token; }
    });

    // Enter sends, Shift+Enter makes a newline.
    var ta = document.querySelector('textarea');
    ta.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        document.querySelector('form.composer button.send').click();
      }
    });

    // Disable Send while a turn is streaming; re-enable when the stream closes.
    var sendBtn = document.querySelector('button.send');
    document.body.addEventListener('htmx:afterSwap', function () {
      var streaming = document.querySelector('.bubble[sse-connect]');
      sendBtn.disabled = !!streaming;
      var thread = document.getElementById('thread');
      thread.scrollTop = thread.scrollHeight;
    });
    // htmx SSE ext dispatches htmx:sseClose when sse-close fires.
    document.body.addEventListener('htmx:sseClose', function () {
      sendBtn.disabled = false;
    });
    // Keep the view pinned to the latest tokens as they stream in.
    document.body.addEventListener('htmx:sseMessage', function () {
      var thread = document.getElementById('thread');
      thread.scrollTop = thread.scrollHeight;
    });

    // If auth fails, tell the user to sign in.
    document.body.addEventListener('htmx:responseError', function (e) {
      if (e.detail.xhr && (e.detail.xhr.status === 401 || e.detail.xhr.status === 403)) {
        var thread = document.getElementById('thread');
        thread.insertAdjacentHTML('beforeend',
          '<div class="msg system"><div class="bubble">Please sign in to Open WebUI and reload this page.</div></div>');
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 3: Sanity-check the page structure (no server needed)**

Run: `grep -nP "[\x{2013}\x{2014}]" mcp-servers/tasks/static/fusion.html`
Expected: no output (no en/em dashes in the copy).
Run: `grep -c "sse-connect=\"/tasks/fusion/stream\"" mcp-servers/tasks/static/fusion.html || true`
Note: the `sse-connect` attribute lives in the SERVER fragment (`_assistant_bubble_streaming`), not in fusion.html; the page only references the endpoints in `hx-post`. Confirm the page has `hx-post="/tasks/fusion/send"` and `hx-post="/tasks/fusion/new"`:
Run: `grep -n "hx-post=\"/tasks/fusion/send\"\|hx-post=\"/tasks/fusion/new\"" mcp-servers/tasks/static/fusion.html`
Expected: both present.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/static/fusion.html mcp-servers/tasks/static/vendor/htmx.min.js mcp-servers/tasks/static/vendor/sse.js
git commit -m "feat(fusion): chat page HTML with vendored HTMX and SSE extension"
```

---

## Task 4: Sidebar nav entry

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` (the `NAV_ENTRIES` array near line 1092)

**Interfaces:**
- Consumes: the existing `NAV_ENTRIES` array shape - each entry is an object with `allUsers`, `label`, `title`, `href`, and (per the existing entries) an icon/glyph field. Match the EXACT shape of the neighbouring App Builder / Video Generation entries.
- Produces: a Fusion nav entry pointing at `/tasks/fusion`.

- [ ] **Step 1: Read the exact existing entry shape**

Run: `sed -n '1092,1140p' mcp-servers/tasks/static/task-panel.js`
Note the exact keys used by the App Builder and Video Generation entries (label, title, href, allUsers, and whatever the icon/svg/glyph key is named). The new entry MUST use the same keys, including the icon key, so it renders identically.

- [ ] **Step 2: Add the Fusion entry**

Insert a new entry into `NAV_ENTRIES`, immediately after the Cron Jobs entry, mirroring the exact key set of the existing entries. Use:
- `allUsers: true`
- `label: "Fusion"`
- `title: "Fusion: ask a panel of models, get one answer"`
- `href: "/tasks/fusion"`
- the icon/glyph key set to a merge/fusion style glyph consistent with how the other entries define their icon (reuse the same field name and a suitable inline SVG or emoji, matching the sibling entries' format exactly).

Do not invent a new key name; whatever the siblings call the icon field, use that.

- [ ] **Step 3: Verify no dashes and the entry is well-formed**

Run: `grep -nP "[\x{2013}\x{2014}]" mcp-servers/tasks/static/task-panel.js`
Expected: no NEW en/em dashes introduced by this change (if the file already had some pre-existing, note them but do not fix unrelated lines; the added Fusion entry must have none).
Run: `node -e "require('fs').readFileSync('mcp-servers/tasks/static/task-panel.js','utf8')" && echo OK`
(If `node` is unavailable, visually confirm the array bracket/comma structure is valid.)
Run: `grep -n "\"/tasks/fusion\"\|'/tasks/fusion'" mcp-servers/tasks/static/task-panel.js`
Expected: the new href present.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(fusion): add Fusion entry to the sidebar navigation"
```

---

## Task 5: Remove the OWUI pipe, its installer, and the internal fusion route

**Files:**
- Delete: `open-webui-functions/fusion_pipe.py`
- Delete: `scripts/install_fusion_pipe.py`
- Delete: `mcp-servers/tasks/routes_fusion.py`
- Delete: `mcp-servers/tasks/tests/test_routes_fusion.py`
- Modify: `mcp-servers/tasks/main.py` (remove the `routes_fusion` import and its `include_router`)

**Interfaces:**
- Consumes: nothing new.
- Produces: a codebase where the only Fusion entry point is the page router. The engine (`fusion_engine.py`) and its tests (`test_fusion_engine.py`) STAY.

- [ ] **Step 1: Confirm nothing else imports the removed pieces**

Run: `grep -rn "routes_fusion\b\|fusion_pipe\|install_fusion_pipe\|api/fusion\|/api/fusion" --include=*.py --include=*.md --include=*.sh . | grep -v "routes_fusion_page"`
Note every hit. The only expected references after removal are in docs/spec/checklist files (fine to leave as historical record) and the files being deleted. Confirm no LIVE code (main.py include, another route) still imports `routes_fusion` other than the line you will remove. `fusion_engine` references are unrelated and must remain.

- [ ] **Step 2: Remove the router wiring from main.py**

In `mcp-servers/tasks/main.py`:
- Delete the import line `from routes_fusion import router as fusion_router`.
- Delete the registration line `app.include_router(fusion_router)` (find it near where the other fusion/execution routers register; confirm the exact line with `grep -n "fusion_router" mcp-servers/tasks/main.py`).

Leave `from routes_fusion_page import router as fusion_page_router` and its `include_router` intact.

- [ ] **Step 3: Delete the files**

```bash
git rm open-webui-functions/fusion_pipe.py scripts/install_fusion_pipe.py mcp-servers/tasks/routes_fusion.py mcp-servers/tasks/tests/test_routes_fusion.py
```

- [ ] **Step 4: Run the suite to confirm nothing broke**

Run: `cd mcp-servers/tasks && python -m pytest -q`
Expected: green. `test_fusion_engine.py` still passes; `test_routes_fusion.py` is gone; `test_routes_fusion_page.py` passes. No import error from `main.py`.

Run: `cd mcp-servers/tasks && python -c "import main"`
Expected: no `ModuleNotFoundError` (confirms the removed import is fully gone and the new router imports cleanly).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(fusion): remove OWUI dropdown pipe, installer, and internal route"
```

---

## Task 6: Final whole-branch review

This task is performed by the controller (subagent-driven-development), not an implementer. Dispatch the final code reviewer against the full branch diff (`scripts/review-package <merge-base> HEAD`), with the Global Constraints above as the attention lens. Priorities for the reviewer:

- SSE reconnect safety: the terminal `close` event, `sse-close="close"` on the assistant bubble, AND the pending-user-turn guard in the stream generator are all present (a miss here means an infinite fusion loop with real API cost).
- Auth: `send`/`stream`/`new` all depend on `current_user`; the page HTML route does not leak anything; the Bearer-header inline JS is correct and the stream relies on the cookie.
- HTML escaping: every user-supplied string and every streamed chunk passes through `_esc` before entering a fragment.
- No en/em dashes anywhere in the diff; no AI attribution in commits.
- The removal is complete: no dangling import of `routes_fusion`, `main` imports cleanly, engine tests still green.

Fix any Critical/Important findings with a single fix subagent, re-run the covering tests, re-review, then proceed to deploy.

---

## Task 7: Deploy and prod pipe-uninstall, then verify

Operational task (controller-run). Follow the repo deploy rules: no git on the server, push changed files via tar-over-ssh, rebuild the tasks image (the app runs from the baked `/app`, not a bind mount), never touch `.env`.

- [ ] **Step 1: Confirm the working tree is clean and main is ready**

```bash
git status
git log --oneline -8
```

- [ ] **Step 2: Push the changed tasks + static files to the server**

Tar and push the new/changed files under `mcp-servers/tasks/` (routes_fusion_page.py, static/fusion.html, static/vendor/htmx.min.js, static/vendor/sse.js, main.py, task-panel.js) and remove the deleted `routes_fusion.py` on the server. Use the documented SSH target and `tar` over ssh (not `scp -r`). Example:

```bash
tar -czf - -C mcp-servers/tasks routes_fusion_page.py main.py static/fusion.html static/vendor/htmx.min.js static/vendor/sse.js static/task-panel.js \
  | ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
    "tar -xzf - -C /root/proxy-server/mcp-servers/tasks && rm -f /root/proxy-server/mcp-servers/tasks/routes_fusion.py"
```

- [ ] **Step 3: Rebuild and recreate the tasks service**

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
  "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 4: Uninstall the OWUI pipe on prod and restart OWUI**

Delete the pipe function row so the dropdown models disappear, then restart OWUI:

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
  "cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -T postgres psql -U openwebui -d openwebui -c \"DELETE FROM function WHERE id='fusion_pipe';\" && docker compose -f docker-compose.unified.yml restart open-webui"
```

(Confirm the psql connection details match the live compose; adjust the DB user/name if the server differs. If unsure, first run a `SELECT id FROM function WHERE id='fusion_pipe';` to confirm the row exists before deleting.)

- [ ] **Step 5: Verify end to end**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
```
Then, signed in to Open WebUI in a browser:
- The sidebar shows the Fusion entry; clicking it loads `/tasks/fusion` (the chat page renders, no console errors, vendored scripts load 200).
- Sending a real prompt streams one synthesized answer; the server logs show a call to `api.openai.com` and `api.anthropic.com` plus the judge.
- A second turn works (multi-turn), and New chat clears the thread.
- The old "Fusion (Quality)" / "Fusion (Budget)" models are GONE from the chat model dropdown.

Record the deployed SHA and outcome in `.superpowers/sdd/progress.md` and the deploy checklist.

---

## Self-Review (completed by plan author)

- **Spec coverage:** page + send + stream + new (Tasks 1-2), fusion.html + vendored JS + inline auth JS (Task 3), nav entry (Task 4), pipe + installer + internal route removal (Task 5), deploy + prod cleanup + verify (Task 7), testing (pytest in Tasks 1-2, engine tests preserved in Task 5). The one deliberate deviation from the spec - serving under `/tasks/fusion` instead of a `/fusion` gateway route - is documented in Global Constraints with the reason (the `/tasks/*` prefix is already routed end to end, avoiding an in-repo gateway edit and an out-of-repo host-Caddy edit; strictly safer). Nav href updated to `/tasks/fusion` accordingly.
- **Placeholder scan:** every code step contains complete code; the only prose-only step is the nav icon (Task 4 Step 2), which is intentional because the icon key name must be read from the live sibling entries rather than guessed.
- **Type/name consistency:** `FusionSession`, `_SESSIONS`, `_get_session`, `_sweep`, `_esc`, `_user_bubble`, `_assistant_bubble_streaming`, `_empty_thread`, `router` defined in Task 1 and consumed by Task 2 with identical names; SSE event names `message`/`close` match between the server (`fusion_stream`), the fragment (`_assistant_bubble_streaming`: `sse-swap="message"` + `sse-close="close"`), and the page JS handlers.
