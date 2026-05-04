# Auto-run preview after successful enhance — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** After a successful Build/enhance, the preview server starts automatically so the iframe is live the moment the user opens the Preview tab — without requiring a manual Run click.

**Architecture:** Single hook in `updateAiBubble()` at the existing `task.status === "completed"` branch. If `previewRunning === false`, fire `POST /preview/start` and reuse the manual-Run success block. On failure, toast + leave Run enabled.

**Tech Stack:** Vanilla JS in `mcp-servers/tasks/static/preview.html`. No backend change.

**Design doc:** `docs/plans/2026-05-04-auto-run-preview-design.md` (read first).

---

## Task 1: Add auto-start hook in `updateAiBubble`

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — function `updateAiBubble`, branch `task.status === "completed"`, immediately after `refreshPreviewIframeIfVisible()` (currently line 6065).

**Context the implementer needs:**
- Page-level state already in scope from the closure: `previewRunning` (line 3105), `previewPort` (3106), `taskId` (page-level), `setStatus(state, label)` (5360), `pollPreviewStatus()` (defined near 5365), `apiFetch(method, path, body?)`, `toast(msg, kind, ms?)`, `refreshPreviewIframeIfVisible()` (6113).
- `taskId` here refers to the **page-level** source task (the closure binding), not the enhance task — `updateAiBubble` does not shadow it. The manual Run handler at line 5379 uses the same identifier the same way, so `/preview/start` resolves identically.
- `task.status === "completed"` is the success state in this codebase. Don't use "succeeded".
- The `task.status === "completed"` block is reached for **every** terminal-success enhance: initial enhance, reply-to-clarification, and chat-driven `BUILD_SUGGESTION`. One hook is enough.

**Step 1: Read the current branch**

Run: open `mcp-servers/tasks/static/preview.html`, read lines 6049-6066. Confirm the branch ends with `refreshPreviewIframeIfVisible();` on its own line, with no other code between that and the `} else if (task.status === "failed") {` on the next line.

**Step 2: Insert the hook**

Edit lines 6065-6066. Replace:

```js
      refreshPreviewIframeIfVisible();
    } else if (task.status === "failed") {
```

with:

```js
      refreshPreviewIframeIfVisible();
      maybeAutoStartPreview();
    } else if (task.status === "failed") {
```

**Step 3: Define `maybeAutoStartPreview` near the manual Run/Stop handlers**

In the same file, find the manual Run handler (currently at line 5379, `$btnRun.addEventListener("click", async function () { … });`). Immediately **after** the `$btnStop` handler block ends (find the closing `});` of the stop handler — currently around line 5414), insert:

```js
  // ── Auto-start preview after a successful enhance ──
  // Fires from updateAiBubble's task.status === "completed" branch. Idempotent
  // by design: if previewRunning is already true, we do nothing — the iframe
  // refresh in updateAiBubble already covers the live-update case. On failure,
  // we toast and leave the Run button enabled so the user can retry manually.
  let _autoStartInFlight = false;
  async function maybeAutoStartPreview() {
    if (previewRunning) return;
    if (_autoStartInFlight) return;
    if (!taskId) return;
    _autoStartInFlight = true;
    setStatus("starting", "Starting…");
    try {
      const res = await apiFetch("POST", "/" + taskId + "/preview/start");
      previewRunning = true;
      previewPort = res.port || null;
      pollPreviewStatus();
      refreshPreviewIframeIfVisible();
    } catch (err) {
      toast("Preview couldn't auto-start: " + (err.message || err), "error", 6000);
      setStatus("idle", "Not running");
      $btnRun.disabled = false;
    } finally {
      _autoStartInFlight = false;
    }
  }
```

**Step 4: Manual smoke test (LOCAL or against deployed server)**

The fastest path is to test against the Hetzner deploy after Task 2. Skip ahead to Task 2 first if no local dev environment, then return for Step 5.

If you do have a local environment:
1. Start the tasks container with the modified file mounted.
2. Open `/tasks/static/preview.html?task=<some-task-id>` for an app whose preview is currently stopped.
3. Verify `previewRunning === false` in DevTools console.
4. Send a Build prompt that produces a small file edit ("change the title to 'X'").
5. When the bubble flips to "Done", confirm:
   - Status pill flips through "Starting…" then "Running" automatically (no Run click).
   - Switching to the Preview tab shows the live app immediately.
6. Inspect the Network tab: confirm exactly one `POST /preview/start` happened automatically.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): auto-start preview after successful enhance

After a Build/enhance completes, fire POST /preview/start automatically
when the preview server isn't running yet. Reuses the manual Run success
block (previewRunning, port, status pill, pollPreviewStatus, iframe
refresh). Failures surface as a single toast and leave the Run button
enabled for retry — the build itself is not affected.

Closes the 'kapoyan ko pindot' UX gap raised in chat: users no longer
need to click Run before they can see the agent's first build.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Deploy to Hetzner

**Why a separate task:** The smoke verification has to happen against the real preview-server pool (port 9100-9119), not local. Static files in this codebase are baked into the image, so a rebuild is required.

**Step 1: SCP the modified static file**

Run from `mcp-servers/tasks/`:

```bash
scp static/preview.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/preview.html
```

Expected: silent success (single-line transfer).

**Step 2: Rebuild + restart the tasks container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -10"
```

Expected: ends with `Container tasks  Started`.

**Step 3: Verify the new code is in the running container**

```bash
ssh root@46.224.193.25 "docker exec tasks grep -n 'maybeAutoStartPreview' static/preview.html"
```

Expected: at least 2 matches (definition + call site).

---

## Task 3: Smoke test on live deployment

**Step 1: Open a project where preview is currently stopped**

In the browser, navigate to `https://ai-ui.coolestdomain.win/tasks/static/preview.html?task=<id>` for any built app. Confirm Preview tab shows the "Run" button (not the iframe).

**Step 2: Hard-refresh** (Ctrl+Shift+R / Cmd+Shift+R) to bust browser JS cache.

**Step 3: Send a Build/enhance**

Type a tiny no-op-ish prompt ("add a comment to the top of index.html saying 'autotest'") and Send.

**Step 4: Confirm**

- The bubble goes through Building… → Done without you touching the Run button.
- The status pill near the Run button flips through Starting… → Running on its own.
- Switch to the Preview tab — the iframe shows the app live.
- Open DevTools Network: exactly one `POST /preview/start` was fired automatically.

**Step 5: Failure-path check**

- Stop the preview manually (click Stop) so `previewRunning = false`.
- SSH-rename the app's index.html so the entry-file lookup will fail:
  ```bash
  ssh root@46.224.193.25 "docker exec tasks mv /workspace/ai_ui/apps/<slug>/index.html /workspace/ai_ui/apps/<slug>/index.html.bak"
  ```
- Send another tiny Build. The build succeeds (the agent will recreate the file or another HTML), but if not — confirm a single error toast says "Preview couldn't auto-start: …", the Run button is clickable, and no second toast on a follow-up enhance.
- Restore: `mv index.html.bak back` (or skip if the agent recreated).

**Step 6: Regression check on Plan mode**

- Switch the dropdown to Plan, send a question.
- Confirm the chat reply renders, but **no** `POST /preview/start` is fired (Plan goes through `/chat`, never reaches the hook).

---

## Acceptance checklist (from design doc §Acceptance)

- [ ] Fresh project's first successful enhance shows live preview without Run click.
- [ ] After the 30-min idle stop, the next enhance auto-starts.
- [ ] Manual Run/Stop still work.
- [ ] `start_preview` 4xx/5xx surfaces a single toast and leaves Run clickable.
- [ ] Plan mode still doesn't trigger any preview start.
