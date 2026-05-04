# Auto-on/auto-off preview lifecycle — design

**Date:** 2026-05-04
**Branch:** `feat/gdrive-gmail-connectors`
**Status:** Approved, ready for implementation plan.

## Problem

Today the preview server has no automatic lifecycle. Users have to click **Run** to start, **Stop** to stop. The earlier auto-run feature (commit `dc233812`) only fires after a successful enhance — first-time visitors to a fresh page still see a static "Run" button. And `IDLE_TIMEOUT = 1800` in `app_runner.py:23` is defined but never used: previews that get started keep running forever until the container restarts. With a 20-port pool this is a real risk under multi-user load.

User intent (Cebuano): *"if user is not that page it automatic off"* — preview should be invisible infrastructure that turns on when needed and off when not.

## Goal

- Preview auto-starts when a user lands on a project page.
- Preview auto-stops 2 minutes after the last user leaves.
- Manual Run/Stop buttons are hidden — the user no longer thinks about preview lifecycle at all.
- Status pill remains as a passive indicator (Starting…, Running · port 9100, Not running).

## Non-goals

- Per-user grace periods. Bucket-empty model is simpler and right for shared previews.
- A "force stop now" admin endpoint surface in the UI. The `/preview/stop` route still exists for power users / scripts.
- Surfacing remaining grace time in the UI. Visual noise.
- Restoring `IDLE_TIMEOUT` use as a backstop. The sweep task IS the backstop.
- A "retry" button on auto-start failure. Per brainstorm Q3, refresh handles it.

## Approach (chosen: Approach 1 — background asyncio sweep)

A single asyncio task spawned at startup loops every 30s. For each slug in `_running`, it prunes stale presence and checks `_empty_since[slug]`: if empty for ≥120s, calls `stop_preview(slug)`. Worst-case stop delay = 2 min (grace) + 30s (sweep) = 2.5 min.

### Why this approach

- Single task, simple bookkeeping (one dict).
- Survives container restart cleanly — all in-memory state rebuilds from page heartbeats.
- Robust to user-closes-laptop case (no graceful unload). Heartbeat just stops; presence TTL drops the entry; sweep notices.

### Why not the alternatives

- **Approach 2 (event-driven on DELETE /presence):** Fragile to container restart mid-grace. Fragile to browsers that fail to send the DELETE beacon (Safari has known sendBeacon issues on some unload events). User closes laptop = no DELETE = preview never stops.
- **Approach 3 (hybrid: DELETE hint + sweep verification):** Adds bookkeeping for marginal latency benefit (sweep runs every 30s anyway).

## Sections

### 1. Backend (sweep task + presence integration)

**Module-level state in `app_runner.py`:**

```python
_empty_since: dict[str, float] = {}  # slug → first-seen-empty timestamp
PRESENCE_GRACE_SECONDS = 120
SWEEP_INTERVAL_SECONDS = 30
```

**One new function in `app_runner.py`:**

```python
async def _idle_sweep_loop(is_slug_empty: Callable[[str], bool]) -> None:
    """Run forever: every 30s, stop previews whose presence has been
    empty for ≥ PRESENCE_GRACE_SECONDS. is_slug_empty is injected so
    app_runner doesn't reach into routes_projects (kept dep-free)."""
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

**Helper in `routes_projects.py`** (no new endpoint):

```python
def is_slug_presence_empty(slug: str) -> bool:
    """True iff no live presence entries exist for slug (after pruning)."""
    _prune(slug)
    return not _PRESENCE.get(slug, {})
```

**Startup hook in `main.py`:**

```python
@app.on_event("startup")
async def _start_idle_sweep():
    from routes_projects import is_slug_presence_empty
    asyncio.create_task(_app_runner._idle_sweep_loop(is_slug_presence_empty))
```

`stop_preview(slug)` already exists in `app_runner.py` and is per-slug correct.

### 2. Frontend (page-load auto-start + hide buttons)

**Auto-start at end of `init()` in `preview.html`:**

```js
// Auto-start the preview when the user opens the page. The presence
// heartbeat keeps it running; the backend's idle-sweep stops it 2 min
// after the last user leaves. No manual Run click needed.
maybeAutoStartPreview();
```

The existing `maybeAutoStartPreview()` (preview.html:5419) is already idempotent (guards on `previewRunning`, `_autoStartInFlight`, `taskId`). Same failure path: toast on error, no retry UI per Q3.

**Hide Run/Stop buttons via CSS only — don't delete the DOM nodes.** JS still references `$btnRun.disabled = ...` in several places (manual click handler, `pollPreviewStatus`, `maybeAutoStartPreview` failure). Removing the DOM would force null-guards everywhere.

In `preview.html`'s `<style>`:

```css
/* Run/Stop buttons retired in favor of automatic on/off. The DOM nodes
   stay so existing JS (pollPreviewStatus, maybeAutoStartPreview) can
   keep flipping their state without null-guards. */
#preview-run, #preview-stop {
  display: none !important;
}
```

The implementer will verify the actual element IDs against the markup and adjust.

**Status pill stays.** Display-only: shows "Starting…", "Running · port 9100" or "Running · static", or "Not running". Users see what's happening; nothing to click.

### 3. Edge cases

| Case | Handling |
|---|---|
| User opens page, server has no preview yet | Auto-start fires from init(). |
| User closes tab gracefully | DELETE /presence via beacon, then sweep within 30s, stop at ~2.5 min worst case. |
| User closes laptop / kills tab without unload | No DELETE; heartbeat stops; presence TTL (20s) prunes; sweep notices. Same 2.5 min. |
| User briefly Cmd-Tabs | Heartbeat keeps firing → `_empty_since` reset → preview stays up. |
| User refreshes mid-session | Brief presence gap (seconds). Next sweep sees presence again → reset → preview untouched. |
| Multiple users on same project | Bucket-empty check covers all users. As long as one stays, preview stays. |
| Auto-start fails | Toast fires (existing path). No retry button. Refresh = retry. |
| Container restart | In-memory state wipes. Sweep respawns on startup. Users still on page heartbeat → presence rebuilds. Auto-start fires on next page load. |
| Existing post-enhance auto-start hook | Idempotent — `if (previewRunning) return`. No conflict. |
| Sweep iteration raises | try/except wraps each iteration. One bad slug doesn't kill the loop. |
| 20-port pool exhaustion | Far less likely with 2-min grace vs unlimited lifetime. If it happens, `start_preview` raises, toast surfaces, user refreshes after waiting. |

### 4. Testing

| Layer | Test | Tool |
|---|---|---|
| Backend unit | `tests/test_idle_sweep.py`: invoke the inner sweep block once with `_running={"alpha":...}`, monkey-patched `time.time` advancing past 120s, `is_slug_empty=lambda s: True` → asserts `stop_preview` was called for alpha. With `is_slug_empty=lambda s: False`, alpha is untouched even after 10 min simulated. | pytest + monkeypatch |
| Backend unit | `is_slug_presence_empty(slug)`: empty bucket → True; fresh entry → False; only stale (>20s old) entries → True after `_prune`. | pytest |
| Frontend manual | Open project A → preview auto-starts (no Run click). Close tab. Wait 3 min. SSH-check `_running` no longer has slug A. Reopen → auto-starts again. | Browser + SSH |
| Frontend regression | Run/Stop buttons NOT visible. Status pill still updates correctly. Post-enhance iframe refresh still works. | Browser |
| Backend integration | Two browser tabs on same slug → close one → preview survives (other still heartbeats). Close second → preview stops within 2.5 min. | Two tabs + SSH |

## Out of scope / follow-ups

- "Force stop now" admin UI surface (route already exists).
- Per-user grace periods.
- Remaining-grace countdown in the UI.
- Resuming `IDLE_TIMEOUT` use.
- Retry button on auto-start failure.

## Acceptance

- [ ] Opening a project page auto-starts the preview without clicking Run.
- [ ] Closing the only tab on a project triggers auto-stop within ~2.5 min (worst case).
- [ ] Run and Stop buttons are not visible in the UI.
- [ ] Status pill still reflects current state correctly (Starting / Running · port / Not running).
- [ ] Two-tab test: closing one keeps the preview alive; closing both stops it.
- [ ] Container restart: sweep task respawns; users still on the page rebuild presence and the preview restarts on next visit.
- [ ] `tests/test_idle_sweep.py` covers the sweep logic.
- [ ] No regressions on post-enhance auto-start, manual /preview/stop API, or the iframe refresh after enhance.
