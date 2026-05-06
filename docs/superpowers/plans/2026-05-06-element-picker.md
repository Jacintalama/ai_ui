# Element Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v1 element picker — clicking an element in the preview iframe drops it as a chip in the chat input that scopes the next AI prompt to that element.

**Architecture:** Server-injected picker script lives inside the preview iframe (gated by `?picker=1`). The script highlights elements on hover, captures one click, and posts a structured payload to the parent. Parent renders a single-slot chip that travels alongside the next `/chat` send as a new optional `selection` form field. The system prompt gains a `SELECTED ELEMENT` block when present.

**Tech Stack:** FastAPI + httpx (server), vanilla JS + postMessage (iframe — no external dependencies), vanilla JS reusing existing chip-strip render path (parent), pytest + httpx.AsyncClient (backend tests), Playwright sync API (iframe-side tests).

**Spec:** `docs/superpowers/specs/2026-05-06-element-picker-design.md`

---

## Spec correction note

The spec assigns the HTML rewriter to `mcp-servers/tasks/routes_tasks.py`, but the actual preview-app route lives in `mcp-servers/tasks/main.py:439-510` (`serve_preview_app`). All rewriter work in this plan targets `main.py`. The `/chat` endpoint and the `SelectionPayload` model still live in `routes_tasks.py` as the spec describes.

---

## File Structure

**New files**

| Path | Purpose |
|---|---|
| `mcp-servers/tasks/static/picker.js` | Iframe-side picker script. Self-contained, vanilla JS, ~180 lines, no external dependencies (selector built inline by `buildSelector`). Stateless and ephemeral — only runs when activated by parent. |
| `mcp-servers/tasks/tests/test_preview_picker_inject.py` | Backend tests: HTML rewriter for `serve_preview_app` (when `?picker=1`, when no `</head>`, when `picker=1` absent). |
| `mcp-servers/tasks/tests/test_chat_selection.py` | Backend tests: `/chat` endpoint with `selection` form field — validation, prompt-block assembly, regression for the no-selection path. |
| `mcp-servers/tasks/tests/test_picker_js.py` | Playwright tests: load picker.js into a fixture HTML page, drive activate/click/ESC/Alt-hover, assert overlay DOM and posted messages. |
| `mcp-servers/tasks/tests/fixtures/picker_harness.html` | Static HTML harness used by `test_picker_js.py`. Contains a known DOM tree (a card with nested elements) and a tiny parent-side message recorder script. |

**Modified files**

| Path | What changes |
|---|---|
| `mcp-servers/tasks/main.py:439-510` | `serve_preview_app`: when serving an `.html` file with `?picker=1` in query params, read the file, splice `<script src="/tasks/static/picker.js?v=${PICKER_JS_VERSION}"></script>` before `</head>`, return as `Response`. Wraps in try/except — falls back to original `FileResponse` on any failure. Static-preview path only (dynamic-preview rewriter deferred — not in v1 scope). |
| `mcp-servers/tasks/routes_tasks.py:958-...` | `chat` handler: add optional `selection: str \| None = Form(default=None)`, parse JSON, validate via new `SelectionPayload` Pydantic model, weave a `SELECTED ELEMENT` block into the assembled system prompt, log selector + tag at INFO when present. |
| `mcp-servers/tasks/static/preview.html` | Add `Select` toggle button to chat input toolbar; add iframe URL `?picker=1` handling; add picker state machine + postMessage handlers; add `pendingSelection` single-slot variable; extend chip-strip render path; extend `submitChat()` to FormData-append `selection`; add ESC handler in parent. |

---

## Pre-flight check

- [ ] **Step 0.1: Confirm pytest-playwright is available**

```bash
cd mcp-servers/tasks
python -c "import playwright.sync_api; print('ok')"
```

If this prints `ok`, skip step 0.2. If `ModuleNotFoundError`, install:

- [ ] **Step 0.2 (only if needed): Install pytest-playwright + browser**

```bash
cd mcp-servers/tasks
pip install pytest-playwright
python -m playwright install chromium
```

- [ ] **Step 0.3: Set DATABASE_URL stub and confirm test collection**

`tests/conftest.py` reads `os.environ["DATABASE_URL"]` at module import time, so any pytest invocation needs that env var even for tests that don't touch the DB. On Windows / PowerShell:

```powershell
$env:DATABASE_URL = 'postgresql://stub:stub@localhost:5432/stub'
python -m pytest tests/test_chat_history.py -q --collect-only
```

Or via the Bash tool:

```bash
DATABASE_URL='postgresql://stub:stub@localhost:5432/stub' python -m pytest tests/test_chat_history.py -q --collect-only
```

Expected: `5 tests collected` (no errors). The stub URL is enough to satisfy the module-level env-var read; tests that actually use the `db_session` fixture would fail at runtime, which is fine — we don't need them to pass here. **All pytest invocations in subsequent tasks must set `DATABASE_URL` to this stub value.**

- [ ] **Step 0.4: Local DB-test limitation — Task 6 implementer note**

Task 6's `test_chat_selection.py` needs an admin user and a source task in the DB. On the Windows dev machine there is no local Postgres, so the canonical pattern from `test_chat_history.py` (which uses the real `db_session` fixture) cannot run end-to-end here. The Task 6 implementer should write tests that mock the dependency layer instead: override `current_admin` via `app.dependency_overrides[current_admin]`, monkeypatch `_get_owned_task` to return a stub task with `built_app_slug="alpha"`, and mock `httpx.AsyncClient.post` for the Anthropic call. This keeps the tests runnable locally without losing coverage of the validation + prompt-assembly logic. Real-DB integration coverage falls to Task 11's manual checklist on Hetzner.

---

## Task 1: HTML rewriter — picker.js injection in serve_preview_app

**Files:**
- Modify: `mcp-servers/tasks/main.py:439-510`
- Test: `mcp-servers/tasks/tests/test_preview_picker_inject.py` (new)

**Goal:** When `?picker=1` is present and the served file is HTML with a `</head>` tag, splice in `<script src="/tasks/static/picker.js?v=1"></script>` immediately before `</head>`. All other cases pass through unchanged.

- [ ] **Step 1: Write failing test for the happy path**

Create `mcp-servers/tasks/tests/test_preview_picker_inject.py`:

```python
"""Picker injection: GET /tasks/preview-app/<slug>/?picker=1 must splice
<script src="/tasks/static/picker.js?v=N"></script> before </head> in served HTML."""
import os
import shutil
import tempfile

import httpx
import main
import pytest
from httpx import ASGITransport


@pytest.fixture
def fake_apps_root(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="aiui-test-picker-")
    try:
        monkeypatch.setattr(main, "_APP_ROOT_FS", tmp)
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _get(url: str):
    transport = ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(url)


async def test_picker_param_injects_script_before_head_close(fake_apps_root):
    slug = "alpha"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    body = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(body)

    resp = await _get(f"/tasks/preview-app/{slug}/?picker=1")
    assert resp.status_code == 200
    text = resp.text
    # Exact tag — pin the static-mount path AND the version query so a regression
    # in either (e.g. dropping ?v=) trips this test.
    assert '/tasks/static/picker.js?v=1' in text
    pos_script = text.find("/tasks/static/picker.js")
    pos_head_close = text.lower().find("</head>")
    assert 0 < pos_script < pos_head_close
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_preview_picker_inject.py::test_picker_param_injects_script_before_head_close -v
```

Expected: FAIL — the response will not contain `/tasks/static/picker.js` because the rewriter doesn't exist yet.

- [ ] **Step 3: Implement the rewriter in main.py**

Add at the top of `main.py` near other module-level constants:

```python
PICKER_JS_VERSION = "1"
```

Replace the static-preview branch of `serve_preview_app` (the `FileResponse(...)` return at the bottom of the function) with:

```python
    ext = _os.path.splitext(target)[1].lower()
    media = _MIME_BY_EXT.get(ext, "application/octet-stream")

    # Picker injection: if the request asks for picker mode AND we're serving
    # HTML, splice <script src="/tasks/static/picker.js?v=N"></script> before </head>.
    # Any failure (binary file, missing </head>, decode error) falls through
    # to the standard FileResponse path — the picker is never load-bearing.
    want_picker = bool(request and request.query_params.get("picker") == "1")
    # Note: the outer `request and request.query_params.get(...)` guard above
    # protects us if FastAPI ever invokes this without a Request injection.
    # Don't refactor `want_picker` away — the kwarg is `Optional[Request] = None`.
    if want_picker and ext in (".html", ".htm"):
        try:
            with open(target, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8")
            head_close_idx = text.lower().find("</head>")
            if head_close_idx >= 0:
                tag = (
                    f'<script src="/tasks/static/picker.js?v={PICKER_JS_VERSION}"></script>'
                )
                rewritten = text[:head_close_idx] + tag + text[head_close_idx:]
                return Response(
                    content=rewritten,
                    media_type=media,
                    headers={"Cache-Control": "no-store"},
                )
            else:
                logger.warning(
                    "picker injection skipped: no </head> in %s/%s",
                    slug,
                    rel,
                )
        except Exception as exc:
            logger.warning(
                "picker injection failed for %s/%s: %s", slug, rel, exc
            )

    return FileResponse(
        target,
        media_type=media,
        headers={"Cache-Control": "no-store"},
    )
```

Confirm `Response` and `logger` are already imported at the top of `main.py`. If `logger` isn't, add `import logging; logger = logging.getLogger(__name__)`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_preview_picker_inject.py::test_picker_param_injects_script_before_head_close -v
```

Expected: PASS.

- [ ] **Step 5: Add edge-case tests**

Append to `tests/test_preview_picker_inject.py`:

```python
async def test_no_picker_param_serves_unmodified(fake_apps_root):
    slug = "beta"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    body = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(body)

    resp = await _get(f"/tasks/preview-app/{slug}/")
    assert resp.status_code == 200
    assert "/tasks/static/picker.js" not in resp.text


async def test_html_without_head_close_serves_unmodified(fake_apps_root, caplog):
    slug = "gamma"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    # Malformed: no </head>. Common with hand-rolled fragments.
    body = "<!doctype html><body>just a fragment</body>"
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(body)

    with caplog.at_level("WARNING"):
        resp = await _get(f"/tasks/preview-app/{slug}/?picker=1")
    assert resp.status_code == 200
    assert "/tasks/static/picker.js" not in resp.text
    assert any("picker injection skipped" in r.message for r in caplog.records)


async def test_picker_param_on_non_html_serves_unmodified(fake_apps_root):
    slug = "delta"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><head></head><body></body></html>")
    css_body = "body { color: red; }"
    with open(os.path.join(app_dir, "style.css"), "w", encoding="utf-8") as f:
        f.write(css_body)

    resp = await _get(f"/tasks/preview-app/{slug}/style.css?picker=1")
    assert resp.status_code == 200
    assert "/tasks/static/picker.js" not in resp.text
    assert resp.text == css_body
```

- [ ] **Step 6: Run the test file**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_preview_picker_inject.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_preview_picker_inject.py
git commit -m "feat(tasks): inject picker.js into preview HTML when ?picker=1"
```

---

## Task 2: picker.js bootstrap — empty file that posts io.picker.ready

**Files:**
- Create: `mcp-servers/tasks/static/picker.js`
- Create: `mcp-servers/tasks/tests/fixtures/picker_harness.html`
- Create: `mcp-servers/tasks/tests/test_picker_js.py`

**Goal:** Establish the Playwright test harness and the bare-minimum picker.js. Picker should post `{type: "io.picker.ready"}` to its parent on load and do nothing else.

- [ ] **Step 1: Create the harness HTML**

Create `mcp-servers/tasks/tests/fixtures/picker_harness.html`:

```html
<!doctype html>
<html>
<head>
  <title>Picker Test Harness</title>
  <style>
    body { font-family: sans-serif; padding: 20px; }
    .card { border: 1px solid #ccc; padding: 16px; border-radius: 8px; width: 240px; }
    .card h3 { margin: 0 0 8px; }
  </style>
</head>
<body>
  <main>
    <article class="card" id="card-1">
      <h3>Frontend</h3>
      <p>Some text inside the card</p>
      <button class="cta" type="button">Hire me</button>
    </article>
  </main>
  <script src="/picker.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write failing Playwright test**

Create `mcp-servers/tasks/tests/test_picker_js.py`:

```python
"""Picker.js behavior tests using Playwright. Loads picker.js into a fixture
HTML page and drives it through the postMessage protocol."""
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from contextlib import contextmanager

import pytest
from playwright.sync_api import sync_playwright

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
STATIC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_a, **_kw):
        pass

    def translate_path(self, path):
        # Serve picker.js from /static/, harness from /fixtures/
        if path == "/picker.js":
            return os.path.join(STATIC, "picker.js")
        if path == "/" or path.endswith("/picker_harness.html"):
            return os.path.join(FIXTURES, "picker_harness.html")
        return os.path.join(FIXTURES, path.lstrip("/"))


@contextmanager
def _server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        httpd.shutdown()


@pytest.fixture
def harness_url():
    with _server() as port:
        yield f"http://127.0.0.1:{port}/picker_harness.html"


def test_picker_posts_ready_on_load(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        # Capture postMessages — script runs in the page, but the harness
        # is loaded as the top frame, so window.parent === window. We listen
        # via window.addEventListener for the ready message.
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)
        msgs = page.evaluate("window.__msgs")
        assert any(m.get("type") == "io.picker.ready" for m in msgs)
        browser.close()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py::test_picker_posts_ready_on_load -v
```

Expected: FAIL — `static/picker.js` doesn't exist yet (404).

- [ ] **Step 4: Create the bootstrap picker.js**

Create `mcp-servers/tasks/static/picker.js`:

```javascript
/* IO Element Picker — iframe-side script.
 *
 * Lifecycle (postMessage protocol — both directions use window.parent):
 *
 *   on load:                      iframe -> parent  io.picker.ready
 *   parent -> iframe:             io.picker.activate
 *   parent -> iframe:             io.picker.deactivate
 *   iframe -> parent (on click):  io.picker.selected   (with payload)
 *   iframe -> parent (on ESC):    io.picker.cancelled
 *
 * State: "inert" (default) -> "listening" -> "inert".
 */
(function () {
  "use strict";

  const TARGET = window.parent;
  if (!TARGET || TARGET === window) return;  // not in an iframe — no-op

  function post(msg) {
    try { TARGET.postMessage(msg, "*"); } catch (_) {}
  }

  // Announce readiness so the parent knows it can send activate.
  post({ type: "io.picker.ready" });

  // Wire the activate/deactivate handlers in later tasks.
})();
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py::test_picker_posts_ready_on_load -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/static/picker.js mcp-servers/tasks/tests/fixtures/picker_harness.html mcp-servers/tasks/tests/test_picker_js.py
git commit -m "feat(picker): bootstrap picker.js with ready handshake + Playwright harness"
```

---

## Task 3: picker.js — activate/deactivate + hover overlay

**Files:**
- Modify: `mcp-servers/tasks/static/picker.js`
- Modify: `mcp-servers/tasks/tests/test_picker_js.py`

**Goal:** Receiving `io.picker.activate` enters listening mode, mounts a hover overlay that follows `mousemove`, and renders a label with the would-be-selected selector. Receiving `io.picker.deactivate` tears it all down. `<html>` and `<body>` are ignored as targets (overlay hidden).

- [ ] **Step 1: Write failing test for activate → overlay appears**

Append to `tests/test_picker_js.py`:

```python
def test_picker_activate_mounts_overlay(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)

        # Hover over the card and confirm the overlay's bounding rect tracks it
        card = page.locator("#card-1")
        card.hover()
        rect = page.evaluate("""
          () => {
            const o = document.getElementById('__io_picker_overlay');
            const r = o.getBoundingClientRect();
            return { w: Math.round(r.width), h: Math.round(r.height) };
          }
        """)
        assert rect["w"] > 50 and rect["h"] > 20

        browser.close()


def test_picker_deactivate_removes_overlay(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.goto(harness_url)
        page.wait_for_function("typeof window.postMessage === 'function'", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.deactivate'}, '*')")
        # Overlay should be removed (or at least detached).
        page.wait_for_selector("#__io_picker_overlay", state="detached", timeout=2000)

        browser.close()
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py -v -k "activate_mounts or deactivate_removes"
```

Expected: both FAIL.

- [ ] **Step 3: Implement activate/deactivate + overlay**

Replace `mcp-servers/tasks/static/picker.js` with:

```javascript
/* IO Element Picker — iframe-side script.
 *
 * Lifecycle (postMessage protocol — both directions use window.parent):
 *
 *   on load:                      iframe -> parent  io.picker.ready
 *   parent -> iframe:             io.picker.activate
 *   parent -> iframe:             io.picker.deactivate
 *   iframe -> parent (on click):  io.picker.selected   (with payload)
 *   iframe -> parent (on ESC):    io.picker.cancelled
 *
 * State: "inert" (default) -> "listening" -> "inert".
 */
(function () {
  "use strict";

  const TARGET = window.parent;
  if (!TARGET || TARGET === window) return;

  const OVERLAY_ID = "__io_picker_overlay";
  const LABEL_ID = "__io_picker_label";
  const Z_TOP = 2147483647;

  let state = "inert";
  let $overlay = null;
  let $label = null;
  let lastTarget = null;

  function post(msg) { try { TARGET.postMessage(msg, "*"); } catch (_) {} }

  function ensureOverlay() {
    if ($overlay) return;
    $overlay = document.createElement("div");
    $overlay.id = OVERLAY_ID;
    Object.assign($overlay.style, {
      position: "fixed",
      pointerEvents: "none",
      outline: "2px solid #4f8df0",
      outlineOffset: "0",
      borderRadius: "4px",
      zIndex: String(Z_TOP),
      display: "none",
      left: "0px", top: "0px", width: "0px", height: "0px",
    });
    document.body.appendChild($overlay);

    $label = document.createElement("div");
    $label.id = LABEL_ID;
    Object.assign($label.style, {
      position: "fixed",
      pointerEvents: "none",
      zIndex: String(Z_TOP),
      background: "#4f8df0",
      color: "#fff",
      font: "11px ui-monospace, Menlo, monospace",
      padding: "2px 6px",
      borderRadius: "4px",
      display: "none",
    });
    document.body.appendChild($label);
  }

  function teardownOverlay() {
    if ($overlay) { $overlay.remove(); $overlay = null; }
    if ($label) { $label.remove(); $label = null; }
    lastTarget = null;
  }

  function pickableTarget(el) {
    if (!el || el === document.documentElement || el === document.body) return null;
    if (el.id === OVERLAY_ID || el.id === LABEL_ID) return null;
    return el;
  }

  function buildSelector(el) {
    // Stable-enough selector for chip labels and prompt context. v1 ships
    // this instead of vendoring @medv/finder — see Task 4 Step 1.
    if (!el) return "";
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && parts.length < 4) {
      const tag = cur.tagName.toLowerCase();
      const id = cur.id ? "#" + cur.id : "";
      const cls = (cur.className && typeof cur.className === "string")
        ? "." + cur.className.trim().split(/\s+/).slice(0, 2).join(".")
        : "";
      let nth = "";
      if (!id && cur.parentElement) {
        const siblings = Array.from(cur.parentElement.children)
          .filter((c) => c.tagName === cur.tagName);
        if (siblings.length > 1) nth = `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      parts.unshift(tag + id + cls + nth);
      if (id) break;
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  function onMouseMove(e) {
    if (state !== "listening") return;
    const el = pickableTarget(document.elementFromPoint(e.clientX, e.clientY));
    if (!el) {
      $overlay.style.display = "none";
      $label.style.display = "none";
      lastTarget = null;
      return;
    }
    if (el === lastTarget) return;
    lastTarget = el;
    const r = el.getBoundingClientRect();
    Object.assign($overlay.style, {
      display: "block",
      left: r.left + "px",
      top: r.top + "px",
      width: r.width + "px",
      height: r.height + "px",
    });
    $label.textContent = buildSelector(el);
    $label.style.display = "block";
    $label.style.left = r.left + "px";
    $label.style.top = Math.max(0, r.top - 18) + "px";
  }

  function activate() {
    if (state === "listening") return;
    state = "listening";
    ensureOverlay();
    document.addEventListener("mousemove", onMouseMove, true);
    document.body.style.cursor = "crosshair";
  }

  function deactivate() {
    if (state === "inert") return;
    state = "inert";
    document.removeEventListener("mousemove", onMouseMove, true);
    document.body.style.cursor = "";
    teardownOverlay();
  }

  window.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.type === "io.picker.activate") activate();
    else if (m.type === "io.picker.deactivate") deactivate();
  });

  post({ type: "io.picker.ready" });
})();
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/picker.js mcp-servers/tasks/tests/test_picker_js.py
git commit -m "feat(picker): activate/deactivate with hover overlay"
```

---

## Task 4: picker.js — click capture + selector building + payload

**Files:**
- Modify: `mcp-servers/tasks/static/picker.js`
- Modify: `mcp-servers/tasks/tests/test_picker_js.py`

**Goal:** A click while listening: build the full payload (selector via the new `buildSelector` helper — see Step 1, no external dependency, tag, attrs, outerHtml truncated to 2KB, allowlist of computed styles, rect, url, pickedAt), post `io.picker.selected`, and deactivate. Capture-phase suppression of `click`, `mousedown`, `mouseup`, `submit` while listening so the click doesn't double-fire underlying handlers.

- [ ] **Step 1: Skip vendored finder for v1 — `buildSelector` is already in place**

The spec mentions `@medv/finder` for stable selectors, but vendoring it cleanly across builds is a yak-shave (UMD/ESM wrapper differences across versions, Windows-vs-Linux toolchain mismatch, no build pipeline in this project). For v1, **`buildSelector` (added in Task 3) is the production selector** — it produces strings like `article.skill-card > h3:nth-of-type(2)`, which is good enough for the chip label and adequate for the prompt's `selector:` field. The model gets the full outerHTML anyway, so selector quality has diminishing returns. A future task can swap in `@medv/finder` if selector quality becomes a real complaint.

If Task 3's `buildSelector` is already adequate for the click payload's `selector` field (which it is — same helper used for the hover label), there is **nothing to do in this step except confirm**. Skip to Step 2.

(Reference implementation, in case Task 3 was edited and `buildSelector` was lost — paste this back in:)

```javascript
  function buildSelector(el) {
    if (!el) return "";
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && parts.length < 4) {
      const tag = cur.tagName.toLowerCase();
      const id = cur.id ? "#" + cur.id : "";
      const cls = (cur.className && typeof cur.className === "string")
        ? "." + cur.className.trim().split(/\s+/).slice(0, 2).join(".")
        : "";
      // nth-of-type only when there are siblings of same tag without an id
      let nth = "";
      if (!id && cur.parentElement) {
        const siblings = Array.from(cur.parentElement.children)
          .filter((c) => c.tagName === cur.tagName);
        if (siblings.length > 1) nth = `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      parts.unshift(tag + id + cls + nth);
      if (id) break;  // unique anchor — stop walking up
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }
```

Confirm `buildSelector(el)` is the only selector helper in `picker.js` (no leftover references to a removed `quickSelectorPreview` or to `finder`). **No vendoring required.**

- [ ] **Step 2: Write failing test for click → selected payload**

Append to `tests/test_picker_js.py`:

```python
def test_picker_click_posts_selected_payload(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)

        page.locator("button.cta").click()
        page.wait_for_function(
            "window.__msgs.some(m => m && m.type === 'io.picker.selected')", timeout=2000
        )

        msg = page.evaluate("""
          window.__msgs.find(m => m && m.type === 'io.picker.selected')
        """)
        assert msg["tag"] == "BUTTON"
        assert "cta" in msg["selector"]
        assert msg["outerHtml"].startswith("<button")
        assert "color" in msg["styles"]
        assert msg["rect"]["w"] > 0
        assert msg["url"].endswith("/picker_harness.html")

        browser.close()


def test_picker_click_outerhtml_truncated(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)

        # Stuff the card with a long string so outerHTML goes way past 2KB.
        page.evaluate("""
          const c = document.getElementById('card-1');
          c.appendChild(document.createTextNode('x'.repeat(10000)));
        """)
        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)
        page.locator("#card-1").click()
        page.wait_for_function(
            "window.__msgs.some(m => m && m.type === 'io.picker.selected')", timeout=2000
        )
        msg = page.evaluate("window.__msgs.find(m => m && m.type === 'io.picker.selected')")
        assert len(msg["outerHtml"]) <= 2200

        browser.close()


def test_picker_click_suppresses_form_submit(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__submitted = false;
          window.addEventListener("submit", () => { window.__submitted = true; }, true);
        """)
        page.goto(harness_url)
        # Wrap the cta button in a form for this test
        page.evaluate("""
          const btn = document.querySelector('button.cta');
          const form = document.createElement('form');
          form.action = 'javascript:void(0)';
          btn.parentNode.insertBefore(form, btn);
          form.appendChild(btn);
          btn.type = 'submit';
        """)
        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)
        page.locator("button.cta").click()
        # Picker fires before form submit; submit must NOT have fired.
        submitted = page.evaluate("window.__submitted")
        assert submitted is False, "form submit should be suppressed by picker capture"

        browser.close()
```

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py -v -k "click_posts or click_outerhtml or click_suppresses"
```

Expected: 3 FAIL.

- [ ] **Step 4: Implement click + payload + suppression**

Append the following helpers to `picker.js` (above `activate()`):

```javascript
  const STYLE_KEYS = [
    "color", "backgroundColor", "padding", "margin",
    "fontSize", "fontFamily", "display", "borderRadius",
    "width", "height",
  ];

  function pickStyles(el) {
    const cs = window.getComputedStyle(el);
    const out = {};
    for (const k of STYLE_KEYS) out[k] = cs[k];
    return out;
  }

  function truncate(s, n) {
    return s.length <= n ? s : s.slice(0, n);
  }

  function buildPayload(el) {
    const r = el.getBoundingClientRect();
    const attrs = {};
    if (el.id) attrs.id = el.id;
    if (el.className && typeof el.className === "string") attrs.class = el.className;
    const selector = buildSelector(el);
    return {
      type: "io.picker.selected",
      selector: truncate(selector || "", 400),
      tag: el.tagName,
      attrs,
      outerHtml: truncate(el.outerHTML || "", 2048),
      styles: pickStyles(el),
      rect: { x: r.x, y: r.y, w: r.width, h: r.height },
      url: location.href,
      pickedAt: Date.now(),
    };
  }

  function suppress(e) {
    if (state !== "listening") return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  function onClick(e) {
    if (state !== "listening") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const el = pickableTarget(document.elementFromPoint(e.clientX, e.clientY));
    if (!el) return;
    post(buildPayload(el));
    deactivate();
  }
```

Then update `activate()` and `deactivate()` to wire/unwire the suppressors:

```javascript
  function activate() {
    if (state === "listening") return;
    state = "listening";
    ensureOverlay();
    document.addEventListener("mousemove", onMouseMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("mousedown", suppress, true);
    document.addEventListener("mouseup", suppress, true);
    document.addEventListener("submit", suppress, true);
    document.body.style.cursor = "crosshair";
  }

  function deactivate() {
    if (state === "inert") return;
    state = "inert";
    document.removeEventListener("mousemove", onMouseMove, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("mousedown", suppress, true);
    document.removeEventListener("mouseup", suppress, true);
    document.removeEventListener("submit", suppress, true);
    document.body.style.cursor = "";
    teardownOverlay();
  }
```

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/static/picker.js mcp-servers/tasks/tests/test_picker_js.py
git commit -m "feat(picker): click capture, selector building, payload assembly"
```

---

## Task 5: picker.js — ESC handling and Alt-hover parent affordance

**Files:**
- Modify: `mcp-servers/tasks/static/picker.js`
- Modify: `mcp-servers/tasks/tests/test_picker_js.py`

**Goal:** ESC while listening posts `io.picker.cancelled` and deactivates. Alt-hover walks one level up the DOM tree from `elementFromPoint` for the duration the key is held. Other keys are NOT suppressed.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_picker_js.py`:

```python
def test_picker_click_without_alt_picks_leaf_regression(harness_url):
    """Guard against the Alt-walk in pickableTarget regressing the
    leaf-pick behavior covered by test_picker_click_posts_selected_payload."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)

        # Click the H3 directly with NO Alt held — must still pick the H3,
        # not its parent ARTICLE.
        page.locator("#card-1 h3").click()
        page.wait_for_function(
            "window.__msgs.some(m => m && m.type === 'io.picker.selected')", timeout=2000
        )
        msg = page.evaluate("window.__msgs.find(m => m && m.type === 'io.picker.selected')")
        assert msg["tag"] == "H3"
        browser.close()


def test_picker_escape_cancels(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)
        page.keyboard.press("Escape")
        page.wait_for_selector("#__io_picker_overlay", state="detached", timeout=2000)

        msgs = page.evaluate("window.__msgs")
        assert any(m.get("type") == "io.picker.cancelled" for m in msgs)
        # Other keys are NOT suppressed: a slash key on body does nothing here
        # but the page must remain responsive — implicit assertion.
        browser.close()


def test_picker_alt_hover_picks_parent(harness_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.add_init_script("""
          window.__msgs = [];
          window.addEventListener("message", (e) => window.__msgs.push(e.data));
        """)
        page.goto(harness_url)
        page.wait_for_function("window.__msgs.some(m => m && m.type === 'io.picker.ready')", timeout=2000)

        page.evaluate("window.postMessage({type: 'io.picker.activate'}, '*')")
        page.wait_for_selector("#__io_picker_overlay", state="attached", timeout=2000)

        # Hover the inner h3 with Alt held; clicking should pick the parent card.
        page.keyboard.down("Alt")
        page.locator("#card-1 h3").click(modifiers=["Alt"])
        page.keyboard.up("Alt")
        page.wait_for_function(
            "window.__msgs.some(m => m && m.type === 'io.picker.selected')", timeout=2000
        )

        msg = page.evaluate("window.__msgs.find(m => m && m.type === 'io.picker.selected')")
        # The parent of the H3 is the .card article.
        assert msg["tag"] == "ARTICLE"
        browser.close()
```

- [ ] **Step 2: Run them to verify failure**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py -v -k "escape or alt_hover or without_alt"
```

Expected: 3 FAIL (escape and alt_hover fail because the handler doesn't exist; the without_alt regression test passes initially because Task 4's `pickableTarget` doesn't yet have the Alt branch — but the goal is to keep it green AFTER Task 5's `pickableTarget` rewrite).

- [ ] **Step 3: Add ESC + Alt handling to picker.js**

Add an `altDown` flag at top scope (next to `state`):

```javascript
  let altDown = false;
```

Update `pickableTarget` so Alt walks up:

```javascript
  function pickableTarget(el) {
    if (!el) return null;
    if (altDown && el.parentElement && el.parentElement !== document.documentElement && el.parentElement !== document.body) {
      el = el.parentElement;
    }
    if (el === document.documentElement || el === document.body) return null;
    if (el.id === OVERLAY_ID || el.id === LABEL_ID) return null;
    return el;
  }
```

Add a key handler:

```javascript
  function onKey(e) {
    if (state !== "listening") return;
    if (e.type === "keydown" && e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      post({ type: "io.picker.cancelled" });
      deactivate();
      return;
    }
    if (e.key === "Alt") {
      altDown = e.type === "keydown";
      // Repaint hover so outline jumps to parent immediately.
      if (lastTarget) {
        const r = lastTarget.getBoundingClientRect();
        const synth = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
        onMouseMove(synth);
      }
    }
  }
```

Wire it in activate/deactivate:

```javascript
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("keyup", onKey, true);
```

Mirror the `removeEventListener` calls in `deactivate()`. Reset `altDown = false` on deactivate.

- [ ] **Step 4: Run them to verify pass**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_picker_js.py -v
```

Expected: 9 passed (6 from Tasks 2–4 + 3 added in this Task — escape, alt_hover, and the without_alt regression).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/picker.js mcp-servers/tasks/tests/test_picker_js.py
git commit -m "feat(picker): ESC cancels and Alt-hover walks parent"
```

---

## Task 6: SelectionPayload model + /chat selection field validation

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py:958-...`
- Create: `mcp-servers/tasks/tests/test_chat_selection.py`

**Goal:** `/chat` accepts `selection: str | None = Form(default=None)`. When present, it is JSON-decoded and validated against the new `SelectionPayload` model. Oversize raw, malformed JSON, or schema violations all return `400`. Existing path (no selection) is untouched.

- [ ] **Step 1: Write failing tests**

Create `mcp-servers/tasks/tests/test_chat_selection.py`. Pattern after `tests/test_chat_history.py` for fixture and mocking style. Sketch:

```python
"""Tests for the /chat endpoint's optional `selection` form field."""
import json
from unittest.mock import patch

import httpx
import pytest
import main
from httpx import ASGITransport


# Reuse whatever auth/session/anthropic-mock fixtures live in conftest.py
# The chat endpoint needs:
#   - an admin user (current_admin dep override)
#   - an existing source task with built_app_slug set
#   - a workspace dir with the slug present
#   - ANTHROPIC_API_KEY env
#   - mocked httpx.AsyncClient.post for the Anthropic call
#
# CANONICAL SETUP TO COPY: mcp-servers/tasks/tests/test_chat_history.py
# defines a fixture (look for `async def test_chat_*` — the fixtures it
# depends on are in conftest.py and a few helper module-level functions
# at the top of the file). Bring over the ANTHROPIC_API_KEY env-var setup,
# the httpx.AsyncClient.post mock that captures the request body, and the
# `_get_owned_task` / `_APP_ROOT_FS` workspace setup.


@pytest.fixture
def authed_chat(monkeypatch, tmp_path):
    """Yield a callable that POSTs to /tasks/chat with overridden deps.
    Returns (response, captured_anthropic_request_body).
    """
    # ... fixture body adapted from existing chat tests ...


def _good_selection():
    return {
        "selector": "main > section.skills > article:nth-of-type(2)",
        "tag": "ARTICLE",
        "attrs": {"class": "skill-card"},
        "outerHtml": "<article class=\"skill-card\"><h3>Frontend</h3></article>",
        "styles": {
            "color": "rgb(34, 34, 34)",
            "backgroundColor": "rgb(255, 255, 255)",
            "padding": "16px",
            "margin": "0 0 12px 0",
            "fontSize": "14px",
            "fontFamily": "Inter, sans-serif",
            "display": "block",
            "borderRadius": "8px",
            "width": "300px",
            "height": "180px"
        },
        "rect": {"x": 120, "y": 240, "w": 300, "h": 180},
        "url": "http://example/preview-app/foo/",
        "pickedAt": 1715000000000
    }


async def test_chat_with_valid_selection_includes_block_in_prompt(authed_chat):
    resp, captured = await authed_chat(
        message="make this blue", selection=json.dumps(_good_selection())
    )
    assert resp.status_code == 200
    # Anthropic system prompt should contain the SELECTED ELEMENT block.
    sys_prompt = captured["system"]
    assert "SELECTED ELEMENT" in sys_prompt
    assert "main > section.skills > article:nth-of-type(2)" in sys_prompt


async def test_chat_with_oversized_selection_returns_400(authed_chat):
    big = _good_selection()
    big["outerHtml"] = "x" * 9000
    resp, _ = await authed_chat(message="hi", selection=json.dumps(big))
    assert resp.status_code == 400
    assert "selection" in resp.text.lower()


async def test_chat_with_malformed_selection_json_returns_400(authed_chat):
    resp, _ = await authed_chat(message="hi", selection="{not json")
    assert resp.status_code == 400


async def test_chat_with_invalid_selection_field_returns_400(authed_chat):
    bad = _good_selection()
    bad.pop("selector")  # required field
    resp, _ = await authed_chat(message="hi", selection=json.dumps(bad))
    assert resp.status_code == 400


async def test_chat_without_selection_works_unchanged(authed_chat):
    resp, captured = await authed_chat(message="hi")
    assert resp.status_code == 200
    assert "SELECTED ELEMENT" not in captured["system"]


async def test_chat_with_selection_and_files(authed_chat, tiny_png_bytes):
    resp, captured = await authed_chat(
        message="explain this",
        selection=json.dumps(_good_selection()),
        files=[("files", ("a.png", tiny_png_bytes, "image/png"))],
    )
    assert resp.status_code == 200
    assert "SELECTED ELEMENT" in captured["system"]
    # The image survives too — last user message has at least one image block.
    last = captured["messages"][-1]["content"]
    assert any(part.get("type") == "image" for part in last)
```

The implementer fills in the `authed_chat` fixture by copying the harness from `tests/test_chat_history.py` (or `test_enhance_endpoint.py` — whichever currently mocks the Anthropic call most cleanly). The mock should capture `system` and `messages` from the request body so the tests can inspect what was sent.

- [ ] **Step 2: Run the new file to verify failure**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_chat_selection.py -v
```

Expected: 6 FAIL (most because `selection` field doesn't exist yet, some because the fixture needs filling in).

- [ ] **Step 3: Add SelectionPayload + validation to routes_tasks.py**

Near the existing `ChatMessageSchema` import/definition area, add:

```python
class SelectionPayload(BaseModel):
    selector: str = Field(..., max_length=400)
    tag: str = Field(..., max_length=40)
    attrs: dict[str, str] = Field(default_factory=dict)
    outerHtml: str = Field(..., max_length=2200)
    styles: dict[str, str] = Field(default_factory=dict)
    rect: dict[str, float] | None = None
    url: str | None = Field(default=None, max_length=2000)
    pickedAt: int | None = None

    model_config = {"extra": "forbid"}


SELECTION_RAW_MAX = 8 * 1024  # 8 KB raw cap before parsing
```

Update the `/chat` signature (around line 959):

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(
    source_task_id: str = Form(...),
    message: str = Form(..., min_length=1, max_length=2000),
    history: str = Form(default="[]"),
    files: list[UploadFile] = File(default_factory=list),
    selection: str | None = Form(default=None),   # NEW
    user: AdminUser = Depends(current_admin),
):
```

Right after the `parsed_history` block, before the file-loop, add selection parsing:

```python
    parsed_selection: SelectionPayload | None = None
    if selection is not None:
        if len(selection) > SELECTION_RAW_MAX:
            raise HTTPException(
                400, f"selection field too large (max {SELECTION_RAW_MAX} bytes)"
            )
        try:
            sel_raw = json.loads(selection)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid selection JSON: {e}")
        try:
            parsed_selection = SelectionPayload.model_validate(sel_raw)
        except ValidationError as e:
            raise HTTPException(400, f"Invalid selection payload: {e.errors()}")
        logger.info(
            "chat: selection present (selector=%s tag=%s task=%s)",
            parsed_selection.selector,
            parsed_selection.tag,
            source_id,
        )
```

**Imports to verify at the top of `routes_tasks.py`:**
- `from pydantic import BaseModel, Field, ValidationError` — `BaseModel` and `Field` are likely already imported (other models in the file use them). Add `ValidationError` if missing.
- `json` is imported inside the `chat` function locally (existing pattern); reuse the same import.
- The module logger is named `logger` (`routes_tasks.py:81`). Use `logger.info(...)` exactly.

**`extra="forbid"` and the `type` discriminator:**
The picker's `io.picker.selected` postMessage includes a `type` field for routing. The parent strips it when storing `pendingSelection` (see Task 9 Step 1 — explicit field-by-field copy, no `type` carried into `pendingSelection`). So the JSON sent to `/chat` does NOT contain `type`, and `extra="forbid"` is correct. **Do not refactor Task 9 Step 1's explicit copy into a `JSON.stringify(m)` shortcut** — that would break this contract.

- [ ] **Step 4: Run validation tests to verify pass**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_chat_selection.py::test_chat_with_oversized_selection_returns_400 tests/test_chat_selection.py::test_chat_with_malformed_selection_json_returns_400 tests/test_chat_selection.py::test_chat_with_invalid_selection_field_returns_400 tests/test_chat_selection.py::test_chat_without_selection_works_unchanged -v
```

Expected: 4 passed. (The two prompt-content tests still fail — wired in Task 7.)

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py mcp-servers/tasks/tests/test_chat_selection.py
git commit -m "feat(chat): accept and validate optional selection form field"
```

---

## Task 7: SELECTED ELEMENT block woven into system prompt

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py` (the `/chat` handler)

**Goal:** When `parsed_selection` is set, insert a `SELECTED ELEMENT` block into the assembled system prompt. Block sits in the system prompt (cached across turns), not the user message.

- [ ] **Step 1: Pin the system-prompt assembly site**

The current `/chat` system prompt is a single multi-line f-string at `routes_tasks.py:1104-1158` that ends with `f"APP FILES:\n{file_listing}"`. The SELECTED ELEMENT block goes **at the top** of this f-string — prepended before the BUILDER persona block — so it sits early in the cached system prompt where it carries the most weight. Confirm the line range with:

```bash
grep -n "APP FILES" mcp-servers/tasks/routes_tasks.py
```

- [ ] **Step 2: Add the block builder**

Above the system-prompt assembly site, define:

```python
def _format_selection_block(sel: SelectionPayload) -> str:
    style_pairs = "; ".join(f"{k}: {v}" for k, v in sel.styles.items())
    attrs_str = " ".join(f'{k}="{v}"' for k, v in sel.attrs.items() if v)
    open_tag = f"<{sel.tag.lower()}{(' ' + attrs_str) if attrs_str else ''}>"
    return (
        "SELECTED ELEMENT\n"
        "The user pointed at this element in their preview. Scope your answer or\n"
        "edit to this element specifically. Don't change other parts of the page\n"
        "unless asked.\n"
        "\n"
        f"  selector:  {sel.selector}\n"
        f"  tag:       {open_tag}\n"
        + (f"  url:       {sel.url}\n" if sel.url else "")
        + "\n"
        "  current outerHTML (truncated):\n"
        f"    {sel.outerHtml}\n"
        "\n"
        "  current computed styles (subset):\n"
        f"    {style_pairs}\n"
    )
```

- [ ] **Step 3: Prepend `selection_block` to the system-prompt f-string**

At the prompt-assembly site (the multi-line f-string ending in `APP FILES:\n{file_listing}`), inject one variable just above:

```python
    selection_block = (
        _format_selection_block(parsed_selection) + "\n\n"
        if parsed_selection else ""
    )
```

Then put `{selection_block}` at the **start** of the f-string so the SELECTED ELEMENT block lands above the BUILDER persona block (where it gets the most attention from the model). Concretely: turn the existing `f"""<existing first line>...""" `  into `f"""{selection_block}<existing first line>..."""`.

Verify by adding a temporary `print(system)` before the Anthropic call, running one of the Task 6 prompt-content tests, and confirming `SELECTED ELEMENT` appears at the top of the printed system string. Remove the print before committing.

- [ ] **Step 4: Run the prompt-content tests to verify pass**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_chat_selection.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py
git commit -m "feat(chat): weave SELECTED ELEMENT block into system prompt"
```

---

## Task 8: preview.html — Select toggle button + iframe URL handling

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`

**Goal:** Add a button labeled `Select` in the chat input toolbar (next to the existing paperclip attach button). Clicking flips an `iframePickerOn` flag. When ON, the iframe `src` includes `?picker=1`; when OFF, it doesn't. CSS-only visual: button gets an `.active` class while ON. No tests — visual + behavior covered by manual checklist later.

- [ ] **Step 0: Preflight grep — verify the preview-frame names**

```bash
grep -n "refreshPreviewFrame\|\\$previewBody\|\\$previewRefresh\|pendingAttachments" \
  mcp-servers/tasks/static/preview.html | head -20
```

Confirm `refreshPreviewFrame()`, `$previewBody`, `$previewRefresh`, and `pendingAttachments` exist with those exact names. If any name differs (e.g. `$preview-body`, `refresh_iframe`), update the references in the rest of this task and Task 9 to match before proceeding.

- [ ] **Step 1: Find the chat input toolbar**

Search `preview.html` for the existing attach button (look for `attach`, `paperclip`, or `pendingAttachments`). The toolbar where you add the Select button is the same row.

- [ ] **Step 2: Add the button HTML**

Insert next to the attach button:

```html
<button type="button" class="btn btn-ghost chat-toolbar-btn" id="picker-toggle"
        aria-pressed="false" title="Click an element in the preview to scope your prompt">
  Select
</button>
```

- [ ] **Step 3: Add CSS for active state**

Inside the appropriate CSS block:

```css
.chat-toolbar-btn { padding: 4px 10px; font-size: 12px; }
.chat-toolbar-btn.active {
  background: rgba(79, 141, 240, 0.15);
  border-color: #4f8df0;
  color: #cfe0ff;
}
```

- [ ] **Step 4: Add the toggle handler + iframe URL logic**

Near the existing iframe handling (`refreshPreviewFrame`), add:

```javascript
let iframePickerOn = false;

const $pickerToggle = document.getElementById("picker-toggle");
$pickerToggle.addEventListener("click", () => {
  iframePickerOn = !iframePickerOn;
  $pickerToggle.classList.toggle("active", iframePickerOn);
  $pickerToggle.setAttribute("aria-pressed", String(iframePickerOn));
  $pickerToggle.textContent = iframePickerOn ? "Selecting…" : "Select";
  // Reload iframe with the new ?picker= state so injection takes effect.
  refreshPreviewFrame();
});
```

Update `refreshPreviewFrame`'s URL build line:

```javascript
const src = "/tasks/preview-app/" + slug + "/?t=" + Date.now() +
            (iframePickerOn ? "&picker=1" : "");
```

- [ ] **Step 5: Manual smoke**

Spin up the tasks service locally OR build + push to Hetzner (see deployment section), open a project's Preview tab, click `Select`. The iframe should reload with `?picker=1` in the URL (visible in DevTools Network panel). The picker.js script should appear in the iframe's `<head>` (Inspector). Hovering the iframe should show the blue overlay outline.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): add Select toggle button that gates ?picker=1 in iframe URL"
```

---

## Task 9: preview.html — postMessage wiring + state machine + chip

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`

**Goal:** Parent listens for `io.picker.ready`/`io.picker.selected`/`io.picker.cancelled` from the iframe. State machine: `off` → `arming` (after toggling on, waiting for `ready`) → `selecting` (after sending `activate`) → `off` (after a selection is received). On `selected`, store the payload as `pendingSelection` and render a chip in the chat-input chip strip. Single slot — picking a second element replaces the first. ESC in the parent also dismisses picker mode.

- [ ] **Step 1: Add module-level state + listener**

Near the new `iframePickerOn` block:

```javascript
let pickerState = "off";   // off | arming | selecting
let pendingSelection = null;
let armingTimer = null;

window.addEventListener("message", (e) => {
  // Only trust messages from the preview iframe.
  const iframe = $previewBody.querySelector("iframe");
  if (!iframe || e.source !== iframe.contentWindow) return;
  const m = e.data || {};
  if (m.type === "io.picker.ready") {
    if (pickerState === "arming") {
      iframe.contentWindow.postMessage({ type: "io.picker.activate" }, "*");
      pickerState = "selecting";
      if (armingTimer) { clearTimeout(armingTimer); armingTimer = null; }
    }
  } else if (m.type === "io.picker.selected") {
    pendingSelection = {
      selector: m.selector, tag: m.tag, attrs: m.attrs,
      outerHtml: m.outerHtml, styles: m.styles, rect: m.rect,
      url: m.url, pickedAt: m.pickedAt,
    };
    renderSelectionChip();
    setPickerOff();
  } else if (m.type === "io.picker.cancelled") {
    setPickerOff();
  }
});
```

- [ ] **Step 2: Replace the toggle handler**

Update the `$pickerToggle` click handler from Task 8:

```javascript
$pickerToggle.addEventListener("click", () => {
  if (pickerState === "off") {
    iframePickerOn = true;
    pickerState = "arming";
    $pickerToggle.classList.add("active");
    $pickerToggle.setAttribute("aria-pressed", "true");
    $pickerToggle.textContent = "Selecting…";
    refreshPreviewFrame();
    // 3s arming timeout — picker.js failed to load or report ready.
    armingTimer = setTimeout(() => {
      if (pickerState === "arming") {
        renderToast("Picker failed to load — refresh the preview and try again.");
        setPickerOff();
      }
    }, 3000);
  } else {
    setPickerOff();
  }
});

function setPickerOff() {
  iframePickerOn = false;
  pickerState = "off";
  if (armingTimer) { clearTimeout(armingTimer); armingTimer = null; }
  $pickerToggle.classList.remove("active");
  $pickerToggle.setAttribute("aria-pressed", "false");
  $pickerToggle.textContent = "Select";
  // Tell the iframe to deactivate (best-effort — it may not be loaded).
  const iframe = $previewBody.querySelector("iframe");
  if (iframe && iframe.contentWindow) {
    try { iframe.contentWindow.postMessage({ type: "io.picker.deactivate" }, "*"); } catch (_) {}
  }
  refreshPreviewFrame();  // strips ?picker=1
}
```

(`renderToast` is whatever existing toast/notification helper preview.html has. If there isn't one, log a console warning — non-blocking is fine for v1.)

- [ ] **Step 3: Add chip rendering + remove control**

Find where attachment chips are rendered (around `pendingAttachments` / `renderAttachmentChips` or similar). Add alongside it:

```javascript
function renderSelectionChip() {
  // Single-slot: clear any existing selection chip, then render the new one.
  const strip = document.getElementById("chat-chip-strip");
  let existing = strip.querySelector(".chip-selection");
  if (existing) existing.remove();
  if (!pendingSelection) return;

  const chip = document.createElement("span");
  chip.className = "chip chip-selection";
  // Truncate selector mid-string with ellipsis if too long.
  const sel = pendingSelection.selector;
  const label = sel.length > 40 ? sel.slice(0, 18) + "…" + sel.slice(-18) : sel;
  chip.innerHTML =
    '<span class="chip-text"></span>' +
    '<button class="chip-remove" type="button" aria-label="Remove selection">×</button>';
  chip.querySelector(".chip-text").textContent = "selected: " + label;
  chip.querySelector(".chip-remove").addEventListener("click", () => {
    pendingSelection = null;
    renderSelectionChip();
  });
  strip.appendChild(chip);
}
```

If `chat-chip-strip` doesn't exist as a single container, identify the parent of the existing attachment chips and use that. The CSS for `.chip-selection` should match the existing attachment chip styling — same border-radius and padding, optionally a slightly different border color so the user can tell it's a selection rather than an image.

```css
.chip-selection { border-color: #4f8df0; color: #cfe0ff; background: rgba(79,141,240,0.08); }
.chip-selection .chip-remove { margin-left: 6px; cursor: pointer; }
```

- [ ] **Step 4: Add ESC handler in parent**

```javascript
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (pickerState !== "off") setPickerOff();
});
```

- [ ] **Step 5: Add iframe-load reset for user-initiated refresh**

The existing preview Refresh button calls `refreshPreviewFrame()`. Augment it so a user-initiated refresh (button click) clears the chip and forces picker off:

Find the `$previewRefresh` click handler and replace with:

```javascript
$previewRefresh.addEventListener("click", () => {
  pendingSelection = null;
  renderSelectionChip();
  setPickerOff();          // also strips ?picker=1 and reloads iframe
});
```

For programmatic reloads (e.g. cache-bust on first build), `refreshPreviewFrame` is called directly without going through this handler — chip survives.

- [ ] **Step 6: Manual smoke**

Build + deploy. Open a project's Preview tab. Click `Select`. Click an element in the iframe. A chip with `selected: <selector>` appears in the chat input chip strip. ESC dismisses picker mode without leaving an orphaned overlay. Clicking `×` on the chip removes it. Picking a second element replaces the first.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): chip rendering, postMessage wiring, picker state machine"
```

---

## Task 10: preview.html — submitChat sends selection in FormData

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (the `submitChat` function around line 6512)

**Goal:** When `pendingSelection` is set at submit time, append `selection: JSON.stringify(pendingSelection)` to the FormData. Cleared in the existing `finally{}` (alongside `clearPendingAttachments()`). The user bubble's render path (around `renderChatBubble`) shows the selection chip inline above the message text, mirroring how attachments render today.

- [ ] **Step 1: Snapshot + append in submitChat**

Inside `submitChat`, near the existing `attachmentsForThisTurn = pendingAttachments.slice()` line:

```javascript
const selectionForThisTurn = pendingSelection;  // single-slot, just hold the ref
```

Pass through `renderChatBubble` opts:

```javascript
renderChatBubble("user", text, {
  attachments: attachmentsForThisTurn,
  selection: selectionForThisTurn,
});
```

Inside the FormData build, after the `for (const a of attachmentsForThisTurn)` loop:

```javascript
if (selectionForThisTurn) {
  fd.append("selection", JSON.stringify(selectionForThisTurn));
}
```

In the `finally{}` block, alongside `clearPendingAttachments()`:

```javascript
pendingSelection = null;
renderSelectionChip();
```

- [ ] **Step 2: Render the selection chip in the user bubble**

In `renderChatBubble`, in the `kind === "user"` branch, after the `chat-attachments` rendering:

```javascript
if (opts && opts.selection) {
  const sel = opts.selection;
  const selRow = document.createElement("div");
  selRow.className = "chat-selection";
  const label = sel.selector.length > 40
    ? sel.selector.slice(0, 18) + "…" + sel.selector.slice(-18)
    : sel.selector;
  selRow.textContent = "selected: " + label;
  body.appendChild(selRow);
}
```

CSS:

```css
.chat-bubble.user .chat-selection {
  font: 11px ui-monospace, Menlo, monospace;
  color: #cfe0ff;
  background: rgba(79,141,240,0.10);
  border: 1px solid rgba(79,141,240,0.4);
  border-radius: 4px;
  padding: 2px 6px;
  display: inline-block;
  margin-bottom: 6px;
}
```

- [ ] **Step 3: Manual smoke**

Build + deploy. Click `Select`, click an element, type "make this blue", send. In DevTools Network panel, confirm the `/chat` request body has a `selection` form field whose JSON includes the selector. The user bubble shows `selected: <selector>` above the message text. The AI reply references the element specifically.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): submitChat sends selection in FormData; chip echoes in user bubble"
```

---

## Task 11: Deploy to Hetzner + manual checklist

**Files:**
- None modified — deployment.

**Goal:** Push picker.js, modified preview.html, modified main.py, modified routes_tasks.py, and the new test files to the Hetzner VPS, rebuild the tasks container, and run through the manual checklist from the spec.

- [ ] **Step 0: Preflight — verify Dockerfile picks up picker.js**

```bash
grep -n "static" mcp-servers/tasks/Dockerfile
```

Confirm there's a line like `COPY static/ /app/static/` (or equivalent that glob-includes the directory). If picker.js is COPY'd, no Dockerfile change is needed. If `static/` is enumerated file-by-file, **add** `picker.js` to the COPY list before proceeding — otherwise the rebuild will succeed but the file will 404 at `/tasks/static/picker.js`.

- [ ] **Step 1: Build the docker image locally** (if you want a sanity check first)

Skipped on this dev machine — Docker Desktop isn't running per project memory. Go straight to SCP + remote build.

- [ ] **Step 2: SCP the changed files to Hetzner**

```bash
HOST=root@46.224.193.25
SCP="scp -o StrictHostKeyChecking=accept-new"

$SCP mcp-servers/tasks/main.py                      $HOST:/root/proxy-server/mcp-servers/tasks/main.py
$SCP mcp-servers/tasks/routes_tasks.py              $HOST:/root/proxy-server/mcp-servers/tasks/routes_tasks.py
$SCP mcp-servers/tasks/static/picker.js             $HOST:/root/proxy-server/mcp-servers/tasks/static/picker.js
$SCP mcp-servers/tasks/static/preview.html          $HOST:/root/proxy-server/mcp-servers/tasks/static/preview.html
```

(Per project memory: prefer individual `scp file host:/path/file` for critical deploys — `scp -r` can silently skip files.)

- [ ] **Step 3: Rebuild the tasks container on Hetzner**

```bash
ssh $HOST "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

(`preview.html` is COPY'd into the image at build time, so the container rebuild is required for the parent UI changes — same constraint applies to `picker.js` since it lives under `static/`.)

- [ ] **Step 4: Run the manual checklist from the spec**

For an existing built portfolio project on `https://ai-ui.coolestdomain.win/tasks`:

- [ ] Open the project's Preview tab.
- [ ] Click the `Select` button — its label becomes `Selecting…`, the iframe URL gains `?picker=1` (visible in DevTools Network), and the iframe content is overlaid with a crosshair cursor.
- [ ] Hover a deeply nested element — a blue outline + selector label tracks it.
- [ ] Click the element — chip appears above the chat input as `selected: <selector>`. Picker mode exits automatically.
- [ ] Click `Select` again, hover a leaf node, hold `Alt` while hovering — outline jumps to the parent.
- [ ] Click `Select`, then press `ESC` — picker mode exits cleanly with no orphaned overlay.
- [ ] Click `Select`, then click `Select` again before picking — toggles off cleanly.
- [ ] Click the iframe Refresh button while a chip is held — chip clears, picker mode is off.
- [ ] Switch to the Files tab while picker is on — picker mode auto-deactivates.
- [ ] Send a chat message with the chip held: "make this blue". The user bubble shows the chip above the message text. The AI's reply references the element. In DevTools Network, the request body has a `selection` form field with the selector.
- [ ] Send a chat message with NO chip — the response is unchanged from the prior behavior. Backwards-compat sanity.

- [ ] **Step 5: Commit any last fix-ups discovered during the smoke**

If the manual checklist surfaces issues, fix them in dedicated follow-up commits (one fix per commit). Re-run the checklist for any item touched.

---

## Out of scope (do NOT implement)

- Build-mode integration (chip in build prompt) — payload is reused but the wiring is a v2.
- Multi-select — single-slot only in v1.
- Cross-origin postMessage with origin allowlist — v2 when picker aims at published apps.
- Screenshot crops in the payload — token-heavy, deferred.
- Dynamic-preview (reverse-proxy) HTML rewriter — v1 single-file apps are static; dynamic-app picker is a follow-up.
- Auto-derived `PICKER_JS_VERSION` from mtime — manual constant is fine.
- Discoverability tooltip for Alt-hover — answered via the spec's open question; not implemented in v1 unless flagged before kickoff.

## What success looks like

- Toggle the Select button → click an element → chip appears in chat input → send "make this blue" → AI's reply scopes to that element.
- Tests: `pytest tests/test_preview_picker_inject.py tests/test_chat_selection.py tests/test_picker_js.py -v` is green.
- Manual checklist passes on production.
- No regressions in existing chat / preview tests.
