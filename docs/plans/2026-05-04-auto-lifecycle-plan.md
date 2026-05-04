# Preview auto-on/auto-off lifecycle — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace manual Run/Stop buttons with automatic lifecycle. Preview auto-starts when a user opens a project page; auto-stops 2 minutes after the last user leaves.

**Architecture:** A 30-second background asyncio sweep in `app_runner.py` checks each running slug against the existing `_PRESENCE` map (per-slug heartbeat from `routes_projects.py`). Empty buckets accumulate `_empty_since` time; ≥120s ⇒ stop. Frontend calls the existing `maybeAutoStartPreview()` helper from `init()`. Run/Stop button DOM nodes stay (so existing JS keeps working) but are hidden via CSS.

**Tech Stack:** Python (asyncio + FastAPI startup hook) for backend; vanilla JS + CSS in `static/preview.html` for frontend.

**Design doc:** `docs/plans/2026-05-04-auto-lifecycle-design.md` (read first if anything is unclear).

---

## Task 1: Backend — sweep loop + presence helper + startup hook

**Files:**
- Modify: `mcp-servers/tasks/app_runner.py` — add `_empty_since`, `PRESENCE_GRACE_SECONDS`, `SWEEP_INTERVAL_SECONDS`, `_idle_sweep_loop` after the existing `stop_preview` function (around line 200).
- Modify: `mcp-servers/tasks/routes_projects.py` — add `is_slug_presence_empty(slug)` near the existing `_prune` function (around line 60).
- Modify: `mcp-servers/tasks/main.py` — add a `@app.on_event("startup")` hook to spawn the sweep task. Pick the location near the existing app instance creation (search for other `@app.on_event` hooks first; if none, add it after `app = FastAPI(...)`).
- Create: `mcp-servers/tasks/tests/test_idle_sweep.py`

### Context the implementer needs

- `_running` is `dict[str, dict]` keyed by slug. `app_runner.py:39` defines it.
- `stop_preview(slug)` is async, idempotent, kills the subprocess, and pops from `_running`. Don't reimplement.
- `_PRESENCE` is in `routes_projects.py:48`, `_prune` at line 52, TTL = 20s. Heartbeats land via `POST /api/projects/<slug>/presence` every ~10s while a page is open.
- The sweep must NOT import `_PRESENCE` directly from `routes_projects` (keeps `app_runner.py` decoupled). Instead, `_idle_sweep_loop` accepts a `Callable[[str], bool]` parameter for the empty check, and `main.py` wires the actual implementation in.
- We're adding a single sweep loop at startup. Don't add a way to stop it — the process owns it for its lifetime.

### Step 1: Write the failing test

Create `mcp-servers/tasks/tests/test_idle_sweep.py`:

```python
"""Tests for the idle-sweep loop that powers auto-stop of presence-empty
previews. Exercises a single sweep iteration's logic directly so we don't
have to wait the real 30s interval."""
import asyncio
import time
from unittest.mock import patch

import app_runner


async def _run_one_sweep_iteration(is_slug_empty):
    """Mirror the inner block of _idle_sweep_loop without the outer
    while/sleep. Returns nothing — caller asserts on _running and
    _empty_since side effects."""
    now = time.time()
    for slug in list(app_runner._running.keys()):
        if is_slug_empty(slug):
            if slug not in app_runner._empty_since:
                app_runner._empty_since[slug] = now
            elif now - app_runner._empty_since[slug] >= app_runner.PRESENCE_GRACE_SECONDS:
                await app_runner.stop_preview(slug)
                app_runner._empty_since.pop(slug, None)
        else:
            app_runner._empty_since.pop(slug, None)


def _seed_static(slug):
    """Pretend slug is running as a static (no subprocess) preview."""
    app_runner._running[slug] = {
        "slug": slug,
        "kind": "static",
        "port": None,
        "proc": None,
        "started": time.time(),
    }


def _cleanup():
    app_runner._running.clear()
    app_runner._empty_since.clear()


async def test_empty_slug_first_sweep_records_timestamp_only():
    """First sweep iteration where presence is empty must record
    _empty_since but NOT stop yet."""
    _cleanup()
    _seed_static("alpha")
    try:
        await _run_one_sweep_iteration(is_slug_empty=lambda s: True)
        assert "alpha" in app_runner._running, "stop fired too early"
        assert "alpha" in app_runner._empty_since
    finally:
        _cleanup()


async def test_empty_slug_after_grace_is_stopped():
    """After the grace window has elapsed, sweep stops the preview."""
    _cleanup()
    _seed_static("beta")
    # Pretend "beta" has been empty since 200s ago — past the 120s grace.
    app_runner._empty_since["beta"] = time.time() - 200
    try:
        await _run_one_sweep_iteration(is_slug_empty=lambda s: True)
        assert "beta" not in app_runner._running, "auto-stop did not fire"
        assert "beta" not in app_runner._empty_since, "_empty_since not cleared"
    finally:
        _cleanup()


async def test_non_empty_slug_resets_timer():
    """If a user comes back during the grace window, the timer must
    reset so we don't stop on the very next sweep."""
    _cleanup()
    _seed_static("gamma")
    app_runner._empty_since["gamma"] = time.time() - 100  # would fire soon
    try:
        await _run_one_sweep_iteration(is_slug_empty=lambda s: False)
        assert "gamma" in app_runner._running, "stop fired despite presence"
        assert "gamma" not in app_runner._empty_since, "timer did not reset"
    finally:
        _cleanup()


async def test_sweep_constants_are_sensible():
    """Locks in the values from the design doc (Q2 grace = 2 min,
    sweep interval = 30s). Catches accidental changes."""
    assert app_runner.PRESENCE_GRACE_SECONDS == 120
    assert app_runner.SWEEP_INTERVAL_SECONDS == 30


# Test: is_slug_presence_empty helper from routes_projects
import routes_projects


def test_is_slug_presence_empty_true_for_empty_bucket():
    routes_projects._PRESENCE.pop("delta", None)
    assert routes_projects.is_slug_presence_empty("delta") is True


def test_is_slug_presence_empty_false_for_fresh_entry():
    routes_projects._PRESENCE["epsilon"]["u@x"] = {
        "last_seen": time.time(),
        "is_building": False,
    }
    try:
        assert routes_projects.is_slug_presence_empty("epsilon") is False
    finally:
        routes_projects._PRESENCE.pop("epsilon", None)


def test_is_slug_presence_empty_true_when_only_stale_entries():
    """Stale entries (>20s old) should be pruned, leaving the bucket
    effectively empty."""
    routes_projects._PRESENCE["zeta"]["u@x"] = {
        "last_seen": time.time() - 100,  # well past the 20s TTL
        "is_building": False,
    }
    try:
        assert routes_projects.is_slug_presence_empty("zeta") is True
    finally:
        routes_projects._PRESENCE.pop("zeta", None)
```

### Step 2: Run test to verify it fails

```bash
cd mcp-servers/tasks
DATABASE_URL=postgresql://dummy:dummy@localhost/dummy AIUI_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -m pytest tests/test_idle_sweep.py -v
```

Expected: 7 failures, all on `AttributeError: module 'app_runner' has no attribute '_empty_since'` / `PRESENCE_GRACE_SECONDS` / `_idle_sweep_loop`, plus `is_slug_presence_empty` doesn't exist yet.

### Step 3: Add backend code in `app_runner.py`

Find the location AFTER the existing `stop_preview` function (search for `async def stop_preview` and find its closing — typically a few function definitions before `def get_status` at line 212). Insert this block:

```python
# Idle-stop sweep — stops previews whose page has had no presence
# heartbeat for PRESENCE_GRACE_SECONDS. Spawned once at app startup.
PRESENCE_GRACE_SECONDS = 120
SWEEP_INTERVAL_SECONDS = 30

_empty_since: dict[str, float] = {}


async def _idle_sweep_loop(is_slug_empty) -> None:
    """Run forever: every SWEEP_INTERVAL_SECONDS, stop previews whose
    presence bucket has been empty for ≥ PRESENCE_GRACE_SECONDS.
    is_slug_empty is injected so this module stays import-free of
    routes_projects."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            now = time.time()
            for slug in list(_running.keys()):
                if is_slug_empty(slug):
                    if slug not in _empty_since:
                        _empty_since[slug] = now
                    elif now - _empty_since[slug] >= PRESENCE_GRACE_SECONDS:
                        logger.info("Auto-stopping idle preview: %s", slug)
                        await stop_preview(slug)
                        _empty_since.pop(slug, None)
                else:
                    _empty_since.pop(slug, None)
        except Exception:
            logger.exception("idle sweep iteration failed")
```

Verify `time` and `asyncio` are already imported at the top of the file (they are, per existing usage).

### Step 4: Add helper in `routes_projects.py`

Find `_prune(slug)` at line 52. Immediately after that function, insert:

```python
def is_slug_presence_empty(slug: str) -> bool:
    """True iff no live presence entries exist for slug (after pruning).
    Used by app_runner._idle_sweep_loop to decide when to auto-stop."""
    _prune(slug)
    return not _PRESENCE.get(slug, {})
```

### Step 5: Wire startup hook in `main.py`

First, search for existing `@app.on_event` hooks: `grep -n '@app.on_event' main.py`. If any exist, add the new one near them. If none, add it after the `app = FastAPI(...)` line.

Insert:

```python
@app.on_event("startup")
async def _start_idle_sweep():
    """Spawn the per-slug auto-stop sweep so previews don't hold ports
    after the last user leaves. See app_runner._idle_sweep_loop."""
    import app_runner as _ar
    from routes_projects import is_slug_presence_empty
    asyncio.create_task(_ar._idle_sweep_loop(is_slug_presence_empty))
```

Verify `asyncio` is imported at the top of `main.py`. If not, add `import asyncio` (it's likely already there given the FastAPI app — confirm before adding).

### Step 6: Run tests to verify they pass

```bash
DATABASE_URL=postgresql://dummy:dummy@localhost/dummy AIUI_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -m pytest tests/test_idle_sweep.py -v
```

Expected: 7 PASS.

### Step 7: Run wider regression check

```bash
DATABASE_URL=postgresql://dummy:dummy@localhost/dummy AIUI_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -m pytest tests/ -x --ignore=tests/test_template_app_copy.py 2>&1 | tail -20
```

Expected: only the previously-known pre-existing failures (`test_get_endpoint_excludes_rules_field`, `test_build_enhance_prompt_forbids_stack_pivot`). Anything new that breaks must be diagnosed and fixed before continuing.

### Step 8: Commit

```bash
git add mcp-servers/tasks/app_runner.py mcp-servers/tasks/routes_projects.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_idle_sweep.py
git commit -m "feat(preview): auto-stop idle previews via 30s presence sweep

Adds _idle_sweep_loop in app_runner.py that stops previews whose
presence bucket has been empty for ≥120s (grace per design doc Q2).
The loop is spawned once at startup via main.py's @app.on_event
hook; routes_projects.is_slug_presence_empty bridges _PRESENCE into
the dependency-free app_runner module.

Replaces the unused IDLE_TIMEOUT=1800 constant — that was defined but
never wired to anything, so previews held ports forever until container
restart. With the 20-port pool, that was a real risk under multi-user
load.

Frontend hookup (page-load auto-start + button hide) lands in the next
commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Frontend — page-load auto-start + hide buttons

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html`:
  - CSS: add `#btn-run, #btn-stop { display: none !important; }` rule near other UI element styles.
  - JS: at end of `init()` (around line 5544), call `maybeAutoStartPreview();`.

### Context the implementer needs

- Button IDs (verified by grep): `#btn-run` and `#btn-stop`. JS references them as `$btnRun` / `$btnStop` (preview.html:3124-3125).
- `maybeAutoStartPreview()` already exists at preview.html:5419. Idempotent: returns early if `previewRunning`, `_autoStartInFlight`, or `!taskId`. Already toasts on failure. No change needed inside the function.
- `init()` is at preview.html:5529-5546. After `loadFileTree`, `startPolling`, `loadLogs`, `loadDatabase`, `loadGraph`. The existing line 5544 is `if (activeTab !== "files") switchTab(activeTab);` — added by an earlier commit. Add the auto-start call AFTER that line.
- Don't delete the button DOM nodes. The JS at preview.html:5339-5414 still toggles `$btnRun.disabled = ...` from multiple places (manual click handler, polling, auto-start failure path). Hiding via CSS is enough.

### Step 1: Add CSS to hide the buttons

Find the existing `<style>` block in `static/preview.html` (it spans many lines). Search for an existing `#btn-` rule, or pick a stable spot near other `.btn` styles. Add:

```css
/* Run/Stop buttons retired in favor of automatic on/off. The DOM nodes
   stay so existing JS (pollPreviewStatus, maybeAutoStartPreview) can
   keep flipping their disabled state without null-guards. */
#btn-run, #btn-stop {
  display: none !important;
}
```

### Step 2: Add page-load auto-start in `init()`

In `init()` at the end of the function body — after the existing `if (activeTab !== "files") switchTab(activeTab);` line and before the closing `}` — add:

```js
    // Auto-start the preview on page load. The presence heartbeat keeps
    // it running; the backend's idle-sweep stops it ~2.5 min after the
    // last user leaves. No manual Run click needed.
    maybeAutoStartPreview();
```

`maybeAutoStartPreview()` is already idempotent and already in scope inside `init()`.

### Step 3: Manual smoke test (best done after Task 3 deploy)

If you have a local dev environment:
1. Open `/tasks/static/preview.html?task=<id>` for any built app.
2. Hard-refresh.
3. Confirm: status pill goes Starting… → Running automatically.
4. Confirm: no Run or Stop buttons visible.
5. Switch to Preview tab — iframe live.
6. Close the tab. Wait 3 min. Reopen. Preview should re-start automatically (because the sweep stopped it and the new auto-start fires).

### Step 4: Commit

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): auto-start on page load + hide Run/Stop buttons

init() now calls the existing idempotent maybeAutoStartPreview() so a
fresh page visit kicks off the preview without a Run click. Run/Stop
buttons are hidden via CSS (DOM nodes preserved so existing JS keeps
flipping their disabled state).

Closes the 'kapoyan ko pindot' UX gap end-to-end: combined with the
backend idle-sweep from the previous commit, preview lifecycle is now
fully automatic — no buttons to click.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Deploy to Hetzner

**Step 1: SCP the modified files**

From `mcp-servers/tasks/`:

```bash
scp app_runner.py routes_projects.py main.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp static/preview.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/preview.html
```

**Step 2: Rebuild + restart the tasks container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -8"
```

Expected: ends with `Container tasks  Started`.

**Step 3: Verify the sweep task spawned**

```bash
ssh root@46.224.193.25 "docker logs tasks --tail 20 2>&1 | head -25"
```

Expected: standard startup logs including `Application startup complete`. The sweep loop runs silently until it actually stops something (then logs `Auto-stopping idle preview: <slug>`).

```bash
ssh root@46.224.193.25 "docker exec tasks python -c 'from app_runner import PRESENCE_GRACE_SECONDS, SWEEP_INTERVAL_SECONDS, _empty_since; print(\"grace:\", PRESENCE_GRACE_SECONDS, \"sweep:\", SWEEP_INTERVAL_SECONDS, \"empty_since:\", _empty_since)'"
```

Expected: `grace: 120 sweep: 30 empty_since: {}`.

```bash
ssh root@46.224.193.25 "docker exec tasks grep -nE 'btn-run.*display: none|maybeAutoStartPreview\\(\\);.*\$' static/preview.html | head -5"
```

Expected: matches confirming both the CSS rule and the new init() call.

---

## Task 4: Smoke test on live deployment

**Step 1: Open a fresh project in the browser** (e.g., the `testing` project or any app with an entry file). Hard-refresh.

**Step 2: Confirm auto-start without clicking anything:**
- Status pill flips through Starting… → Running.
- Switch to Preview tab — iframe is live.
- DevTools Network: exactly one `POST /preview/start` fired automatically.
- No Run or Stop buttons visible anywhere.

**Step 3: Multi-tab test:**
- Open the same project in a second tab. Confirm both tabs see "Running" pill.
- Close the second tab. After ~30s, confirm the first tab still shows Running (one user is still here).

**Step 4: Auto-stop test:**
- Close all tabs for that project. Wait 3 minutes (covers grace + sweep delay).
- SSH check:
  ```bash
  ssh root@46.224.193.25 "docker exec tasks python -c 'import app_runner; print(list(app_runner._running.keys()))'"
  ```
- Expected: the slug is no longer in `_running`.
- Tasks logs should show: `Auto-stopping idle preview: <slug>`.

**Step 5: Reopen the project page:**
- Auto-start fires again. Status pill goes Starting… → Running.

**Step 6: Regression checks:**
- Existing `/preview/stop` API still works for power users (try `curl` against it; preview stops).
- After an enhance, the iframe still updates without manual click (existing post-enhance auto-start hook still works — same `maybeAutoStartPreview` it's been calling).

---

## Acceptance checklist (from design doc §Acceptance)

- [ ] Opening a project page auto-starts the preview without clicking Run.
- [ ] Closing the only tab triggers auto-stop within ~2.5 min.
- [ ] Run and Stop buttons not visible in the UI.
- [ ] Status pill still reflects current state correctly.
- [ ] Two-tab test: closing one keeps the preview alive; closing both stops it.
- [ ] Container restart: sweep task respawns; users still on the page rebuild presence.
- [ ] `tests/test_idle_sweep.py` covers the sweep + presence-empty logic.
- [ ] No regressions on post-enhance auto-start, manual `/preview/stop` API, or iframe refresh after enhance.
