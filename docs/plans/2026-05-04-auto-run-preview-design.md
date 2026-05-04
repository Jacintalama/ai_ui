# Auto-run preview after successful enhance — design

**Date:** 2026-05-04
**Branch:** `feat/gdrive-gmail-connectors`
**Status:** Approved, ready for implementation plan.

## Problem

Today the App Builder's preview only runs after the user clicks **Run** on the Preview tab. The iframe-refresh-after-enhance plumbing already works (`refreshPreviewIframeIfVisible()` at `preview.html:6065`), but it's a no-op until an iframe exists, which only happens after a manual Run click.

Result: every fresh app, and every app whose preview hit the 30-minute idle stop, requires one ceremonial click before the user can see what the agent built. A user (Cebuano feedback: *"kapoyan ko pindot"* — "I'm tired of clicking") asked for this to be automatic.

## Goal

After a successful Build/enhance, the preview server starts automatically so the iframe is live the moment the user switches to the Preview tab. Manual Run/Stop stays for control + recovery.

## Non-goals

- Replacing the manual Run/Stop buttons. They stay as a control + recovery surface.
- Auto-start on page load (Approach B in brainstorm). Costs ports/RAM before the user has done anything.
- A backend SSE/WebSocket layer (Approach C). Massive scope vs. the size of this UX win.
- A user-facing "disable auto-start" toggle. YAGNI until someone asks.

## Approach (chosen: A — frontend hook)

Hook into the existing enhance-success branch in `pollEnhance`, where we already call `refreshPreviewIframeIfVisible()`. If `previewRunning === false`, fire `POST /preview/start` and reuse the existing manual-Run success block (`previewRunning = true`, `previewPort = res.port`, `setStatus("running", …)`, `pollPreviewStatus()`).

### Why this approach

- ~15 lines of JS, no backend change.
- Reuses every existing helper: `apiFetch`, `setStatus`, `toast`, `pollPreviewStatus`, `refreshPreviewIframeIfVisible`.
- Inherits the existing failure paths (toast + Run button stays clickable).
- Single hook covers all three enhance entry points: initial enhance, reply-to-clarification, chat-driven `BUILD_SUGGESTION`.

### Why not the alternatives

- **B (eager start at submitEnhance):** spends a port and RAM even when the build fails or is cancelled. The 20-port pool is a real cap.
- **C (backend SSE):** months of infra for a one-day feature. Can be revisited if frontend polling proves flaky.

## Sections

### 1. Hook point and trigger

- File: `mcp-servers/tasks/static/preview.html`
- Function: `updateAiBubble()`, `task.status === "succeeded"` branch (current ~line 6065).
- Trigger: `task.status === "succeeded" && previewRunning === false`.
- "Successful enhance" comes from the existing `phase.terminal` check; cancelled/failed tasks never enter this branch.

### 2. Behavior

**Success path:**

1. Existing code runs: render bubble content, suggestions, commit SHA, then call `refreshPreviewIframeIfVisible()` (no-op if iframe absent).
2. **New:** if `!previewRunning`, `await apiFetch("POST", "/" + taskId + "/preview/start")`.
3. On 200: `previewRunning = true`, `previewPort = res.port || null`, `setStatus("running", …)`, `pollPreviewStatus()`.
4. Call `refreshPreviewIframeIfVisible()` again so the iframe hydrates with the new port.
5. **No success toast.** The enhance bubble already shows "done"; another toast would be noise.

**Failure path:**

1. Catch the start error.
2. `toast("Preview couldn't auto-start: " + err.message, "error", 6000)` — wording matches the manual handler at `preview.html:5393`.
3. Leave `previewRunning = false`, `$btnRun.disabled = false`. User can click **Run** to retry.
4. Do **not** mark the enhance as failed. The build itself succeeded; only the preview side-effect failed.

### 3. Edge cases

| Case | Handling |
|---|---|
| Concurrent enhances on same slug | `/enhance` already 409s; never two success hooks at once. |
| Manual Run click while auto-start in flight | `app_runner._running` is keyed by slug; the second `start_preview` returns the existing port (idempotent). |
| Tab on Logs/Files/Structure when success fires | `refreshPreviewIframeIfVisible()` early-returns; iframe hydrates on next `switchTab("preview")`. |
| 30-min idle stop afterward | Next enhance auto-starts again. Desired. |
| User cancels mid-build | `phase.terminal` enters via failed branch; hook doesn't fire. |
| Auth expires during polling | `apiFetch` 401 path handles it; toast surfaces "Session expired". |
| App has no entry file | `start_preview` → `FileNotFoundError` → 404 → toast: "no runnable entry file". |

### 4. Testing

| Layer | Test | How |
|---|---|---|
| Manual smoke | Fresh app, first enhance, Preview tab live without clicking Run | Browser vs deployed server |
| Manual regression | Stop still works; manual Run while running still 200s | Same |
| Manual failure | Remove `index.html` mid-build (SSH), confirm toast + Run button clickable | SSH + browser |
| Unit | None — added JS is small, glue-only, no logic to isolate | — |

## Out of scope / follow-ups

- "Disable auto-start" toggle.
- Eager start at `submitEnhance` time.
- Backend-driven start via SSE.
- Surfacing the auto-started port in the Run button label (cosmetic).

## Acceptance

- [ ] After a fresh project's first successful enhance, the Preview tab shows the live app without clicking Run.
- [ ] After a 30-min idle stop, the next successful enhance auto-starts the preview.
- [ ] Manual Run/Stop buttons still work.
- [ ] When `start_preview` 4xx/5xx, a single error toast surfaces and Run stays clickable.
- [ ] No regression in Plan mode (which never reaches this hook).
