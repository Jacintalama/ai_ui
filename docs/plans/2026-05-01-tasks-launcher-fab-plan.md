# Tasks Launcher FAB — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the auto-popping center modal of the admin tasks panel with a persistent floating launcher icon at the bottom-right of the viewport that opens / collapses the panel. Mobile gets a bottom-sheet layout.

**Architecture:** Pure client-side change in `mcp-servers/tasks/static/task-panel.js`. Add a new floating `<button>` (the FAB) appended to `document.body`, and reposition the existing panel to anchor above it. No backend changes. No new dependencies. The FAB is the only auto-visible affordance; the panel itself only shows when the user clicks the FAB (or the existing `+` integrations menu entry, kept as a redundant entry point).

**Tech Stack:** Vanilla JS + CSS, served as a static asset by the FastAPI tasks service and injected into Open WebUI via `<script src="/tasks/static/task-panel.js">` in `openwebui-overrides/index.html`.

**Reference design doc:** `docs/plans/2026-05-01-tasks-launcher-fab-design.md`

**Testing reality:** There is no JS test harness for this file. Each task includes manual verification via browser (load `https://ai-ui.coolestdomain.win/` after deploy, or use Playwright). Commits should be small and logical so a regression can be bisected.

---

## Task 1: Add the FAB CSS

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — append FAB rules to the existing `css` template literal (around line 29-96)

**Step 1: Add the new CSS rules**

Append the following to the end of the `css` template literal in `task-panel.js` (just before the closing `` ` ``):

```css
/* ===== FAB launcher ===== */
.aiui-tp-fab {
  position: fixed; bottom: 24px; right: 24px; z-index: 9998;
  width: 44px; height: 44px; border-radius: 50%;
  background: #1a1a1a; border: 1px solid #2a2a2a;
  color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04);
  transition: transform 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.aiui-tp-fab:hover { background: #232323; transform: translateY(-1px); }
.aiui-tp-fab:active { transform: translateY(0); }
.aiui-tp-fab.hidden { display: none; }
.aiui-tp-fab svg { width: 20px; height: 20px; stroke: currentColor; fill: none; stroke-width: 2; }
.aiui-tp-fab .aiui-tp-fab-badge {
  position: absolute; top: -4px; right: -4px;
  min-width: 18px; height: 18px; padding: 0 5px;
  border-radius: 9px; background: #ef4444; color: #fff;
  font-size: 11px; font-weight: 700; line-height: 18px;
  text-align: center; border: 2px solid #0b0b0b;
  box-sizing: content-box;
}
.aiui-tp-fab .aiui-tp-fab-badge.zero { display: none; }
.aiui-tp-fab.pulse { animation: aiui-tp-fab-pulse 1.6s ease-out 2; }
@keyframes aiui-tp-fab-pulse {
  0%   { box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 0 rgba(239,68,68,0.55); }
  70%  { box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 14px rgba(239,68,68,0); }
  100% { box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 0 rgba(239,68,68,0); }
}
@media (max-width: 640px) {
  .aiui-tp-fab { width: 48px; height: 48px; bottom: 16px; right: 16px; }
}
```

**Step 2: Sanity-check the JS still parses**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output (success).

**Step 3: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks-panel): add FAB launcher CSS"
```

---

## Task 2: Build the FAB DOM and append to body

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — add new code right after the existing `document.body.appendChild(panel);` line (around line 129)

**Step 1: Insert the FAB construction**

After `document.body.appendChild(panel);`, add:

```javascript
  // ===== Build FAB launcher =====
  const fab = document.createElement("button");
  fab.type = "button";
  fab.className = "aiui-tp-fab hidden";
  fab.setAttribute("aria-label", "Open tasks panel");
  fab.title = "Tasks";
  fab.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4h6a2 2 0 0 1 2 2v0H7v0a2 2 0 0 1 2-2z"/>
      <rect x="5" y="6" width="14" height="14" rx="2"/>
      <path d="M9 11l2 2 4-4"/>
    </svg>
    <span class="aiui-tp-fab-badge zero" data-role="fab-badge">0</span>
  `;
  document.body.appendChild(fab);
```

**Step 2: Verify no syntax error**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 3: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks-panel): add FAB launcher DOM"
```

---

## Task 3: Wire FAB click and panel close to toggle visibility

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — add a helper, update the close handler, update `window.aiuiTaskPanel.open`

**Step 1: Add a `setOpen(open)` helper near the existing header click handler**

Insert above the existing `panel.addEventListener("click", e => {` block (around line 885):

```javascript
  function setOpen(open) {
    if (open) {
      panel.classList.remove("hidden");
      fab.classList.add("hidden");
    } else {
      panel.classList.add("hidden");
      fab.classList.remove("hidden");
    }
  }
```

**Step 2: Wire FAB click**

After `document.body.appendChild(fab);` (added in Task 2), add:

```javascript
  fab.addEventListener("click", () => {
    setOpen(true);
  });
```

**Step 3: Update the existing close handler in the panel click listener**

Find this block (around line 891):

```javascript
    else if (act === "close") {
      panel.classList.add("hidden");
      try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (_) {}
    }
```

Replace with:

```javascript
    else if (act === "close") {
      setOpen(false);
    }
```

**Step 4: Update `window.aiuiTaskPanel.open`**

Find:

```javascript
  window.aiuiTaskPanel = {
    open: () => panel.classList.remove("hidden"),
    refresh: refreshAll,
    state,
  };
```

Replace with:

```javascript
  window.aiuiTaskPanel = {
    open: () => setOpen(true),
    close: () => setOpen(false),
    refresh: refreshAll,
    state,
  };
```

**Step 5: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 6: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks-panel): wire FAB toggle for panel visibility"
```

---

## Task 4: Update count badge from refresh data

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — extend `render()` (around line 159)

**Step 1: Update badge inside `render()`**

Find this block at the top of `render()`:

```javascript
    const total = t.pending.length;
    $(".aiui-tp-title").textContent = total ? `${total} Pending Task${total === 1 ? "" : "s"}` : "No Pending Tasks";
    $('[data-role="badge"]').textContent = total;
```

Add immediately after it:

```javascript
    const fabBadge = fab.querySelector('[data-role="fab-badge"]');
    if (fabBadge) {
      fabBadge.textContent = total;
      fabBadge.classList.toggle("zero", total === 0);
    }
```

**Step 2: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 3: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks-panel): show pending count on FAB badge"
```

---

## Task 5: Replace auto-popup with FAB-visible-on-init

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — `init()` function (around line 946)

**Step 1: Rewrite the auto-popup block**

Find this block inside `init()`:

```javascript
      // Only auto-popup on the very first page load. SPA navigations (clicking
      // around inside OpenWebUI) MUST NOT re-open the panel; the user can use
      // the integrations menu button or Settings toggle to re-open manually.
      if (!_firstLoad) {
        console.log("[AIUI tasks] SPA init — data refreshed, not auto-showing");
        return;
      }
      _firstLoad = false;

      if (!isAutoShowEnabled()) {
        console.log("[AIUI tasks] auto-show disabled by admin");
        return;
      }
      if (state.tasks.pending.length > 0 || state.tasks.done.length > 0) {
        panel.classList.remove("hidden");
      } else {
        console.log("[AIUI tasks] panel hidden — no tasks at all");
      }
```

Replace with:

```javascript
      // Show the FAB launcher; the panel itself stays collapsed until the
      // user clicks the FAB (or the + menu entry).
      fab.classList.remove("hidden");
```

Also remove the now-unused locals: delete the line `let _firstLoad = true;` (around line 944).

**Step 2: Hide the FAB on auth route as well**

In `watchSpaNavigation`, find:

```javascript
      if (onAuthRoute()) {
        panel.classList.add("hidden");
      } else {
```

Replace with:

```javascript
      if (onAuthRoute()) {
        panel.classList.add("hidden");
        fab.classList.add("hidden");
      } else {
```

**Step 3: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "refactor(tasks-panel): show FAB on init, no more center auto-popup"
```

---

## Task 6: Anchor the panel to bottom-right (slide up from FAB)

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — `.aiui-tp` CSS rule (line 30) and the panel slide-in keyframe (line 36)

**Step 1: Update `.aiui-tp` positioning**

Find:

```css
.aiui-tp { position: fixed; top: 24px; right: 24px; width: 520px; max-height: 78vh;
```

Replace with:

```css
.aiui-tp { position: fixed; bottom: 80px; right: 24px; width: 520px; max-height: 78vh;
```

**Step 2: Update the slide-in animation**

Find:

```css
@keyframes aiui-tp-in { from { opacity: 0; transform: translateY(-10px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
```

Replace with:

```css
@keyframes aiui-tp-in { from { opacity: 0; transform: translateY(12px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
```

**Step 3: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "style(tasks-panel): anchor panel to bottom-right above FAB"
```

---

## Task 7: Mobile bottom-sheet layout

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — append a `@media (max-width: 640px)` block to the panel CSS

**Step 1: Append mobile media query**

Add to the end of the main CSS template literal (before the new FAB rules added in Task 1, or after — order doesn't matter as long as it's inside the same template literal):

```css
@media (max-width: 640px) {
  .aiui-tp {
    left: 0; right: 0; bottom: 0; top: auto;
    width: 100%; max-height: 85vh;
    border-radius: 16px 16px 0 0;
    border-left: 0; border-right: 0; border-bottom: 0;
  }
  .aiui-tp::before {
    content: "";
    display: block;
    width: 36px; height: 4px;
    background: #2a2a2a;
    border-radius: 2px;
    margin: 8px auto 0;
  }
  .aiui-tp-head { padding: 10px 16px 12px; }
  .aiui-tp-body { padding: 12px; }
}
```

**Step 2: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 3: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "style(tasks-panel): mobile bottom-sheet layout"
```

---

## Task 8: Pulse the FAB when pending count increases

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — track previous count in state, trigger pulse class

**Step 1: Add `lastPendingCount` to state**

Find:

```javascript
  const state = { activeTab: "pending", tasks: { pending: [], progress: [], done: [] }, sse: {} };
```

Replace with:

```javascript
  const state = { activeTab: "pending", tasks: { pending: [], progress: [], done: [] }, sse: {}, lastPendingCount: 0 };
```

**Step 2: Trigger pulse in `render()`**

After the FAB-badge update added in Task 4, add:

```javascript
    if (total > state.lastPendingCount && fab.classList.contains("hidden") === false) {
      fab.classList.remove("pulse");
      // Force reflow so the animation restarts when re-added
      void fab.offsetWidth;
      fab.classList.add("pulse");
    }
    state.lastPendingCount = total;
```

**Step 3: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks-panel): pulse FAB when pending count increases"
```

---

## Task 9: Remove the minimize button, dismiss key, and autoshow toggle

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js`

**Step 1: Remove the minimize button from the panel header HTML**

Find in `panel.innerHTML` (around line 117):

```html
        <button data-act="min" title="Minimize">─</button>
```

Delete that line.

**Step 2: Remove the minimize click handler**

Find in the panel click listener (around line 890):

```javascript
    else if (act === "min") panel.classList.toggle("minimized");
```

Delete that line.

Also delete:

```javascript
    else if (panel.classList.contains("minimized") && !e.target.closest("button")) {
      panel.classList.remove("minimized");
    }
```

**Step 3: Remove minimize CSS**

Delete these CSS rules from the `css` template literal:

```css
.aiui-tp.minimized { width: auto; max-height: none; }
.aiui-tp.minimized .aiui-tp-tabs, .aiui-tp.minimized .aiui-tp-body, .aiui-tp.minimized .aiui-tp-foot { display: none; }
```

And:

```css
.aiui-tp.minimized .aiui-tp-head .badge { display: inline-block; }
```

**Step 4: Remove DISMISS_KEY constant**

Find (around line 16-17):

```javascript
  const DISMISS_KEY = "aiui-tasks-dismissed-at";
  const DISMISS_TTL_MS = 4 * 60 * 60 * 1000; // 4 hours
```

Delete both lines.

**Step 5: Remove the autoshow toggle from the `+` menu entry**

In `injectIntegrationsMenuEntry`, delete the entire `// Right side: inline auto-show toggle` block (the toggle button construction + `entry.appendChild(toggle)` line). Keep `entry.appendChild(leftSide);` and the `menu.insertBefore(entry, row);` lines.

Also delete the helper functions if they have no other callers:

```javascript
  const AUTOSHOW_KEY = "aiui-tasks-autoshow";
  function isAutoShowEnabled() { ... }
  function setAutoShow(enabled) { ... }
```

(Search for any other usages first; if none remain, delete.)

**Step 6: Verify**

Run: `node --check mcp-servers/tasks/static/task-panel.js`
Expected: no output.

Then grep for stragglers:

```bash
grep -n "DISMISS_KEY\|AUTOSHOW_KEY\|isAutoShowEnabled\|setAutoShow\|minimized" mcp-servers/tasks/static/task-panel.js
```

Expected: no matches (or only matches inside this comment if you leave any explanation behind).

**Step 7: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "refactor(tasks-panel): remove minimize, dismiss-key, autoshow toggle"
```

---

## Task 10: Bump the cache-bust query string

**Files:**
- Modify: `openwebui-overrides/index.html:206`

**Step 1: Bump the version**

Find:

```html
<script src="/tasks/static/task-panel.js?v=20260425-oi"></script>
```

Replace with:

```html
<script src="/tasks/static/task-panel.js?v=20260501-fab"></script>
```

**Step 2: Commit**

```bash
git add openwebui-overrides/index.html
git commit -m "chore(overrides): bump task-panel.js cache-bust for FAB launcher"
```

---

## Task 11: Manual end-to-end verification

This task is run **after** Task 10 has been deployed to the VPS (via the team's normal SCP + `docker compose build` flow). Skip if executing the plan locally.

**Step 1: Open `https://ai-ui.coolestdomain.win/` in a desktop browser**

Sign in as an admin (e.g. `alamajacintg04@gmail.com`).

Expected:
- No center popup on first load.
- A small dark circular FAB at the bottom-right corner.
- A red badge on the FAB showing the pending count (or no badge if zero).

**Step 2: Click the FAB**

Expected:
- FAB hides.
- Panel slides up from the bottom-right corner with the existing tabs (Pending / In Progress / Done).

**Step 3: Click the `✕` close button on the panel**

Expected:
- Panel slides away.
- FAB reappears with the same count.

**Step 4: Open via the `+` integrations menu**

Click the `+` icon in the chat input → click "Tasks".

Expected:
- Panel opens (FAB hides). Toggle from before is gone.

**Step 5: Mobile test**

Open Chrome DevTools, switch to a 390 × 844 mobile profile, reload.

Expected:
- FAB at bottom-right (slightly larger 48 × 48).
- Click FAB → panel slides up as full-width bottom sheet with rounded top corners and a drag-handle bar.
- Tap the `✕` → sheet slides down, FAB reappears.

**Step 6: Pulse test**

In a second admin session, create a new pending task (e.g. via `POST /api/tasks` or the `+` button inside the panel). After ~10 s, the first session's FAB should pulse briefly when its next refresh notices the count increase.

**Step 7: Sign out**

Expected:
- Both panel and FAB hide.
- No errors in the console.

If any step fails, file as a separate fix commit on top of this branch.

---

## Out of scope

- Animation polish beyond the simple slide-up + 2-cycle pulse.
- Keyboard shortcut to toggle (e.g. `Ctrl+Shift+T`) — could be a follow-up.
- Persisting "panel was open" state across reloads — deliberately starts collapsed every time.
- Reskinning the inner task cards.
- Backend changes — none needed.

## Files changed (final list)

- `mcp-servers/tasks/static/task-panel.js` (Tasks 1–9)
- `openwebui-overrides/index.html` (Task 10)
- `docs/plans/2026-05-01-tasks-launcher-fab-design.md` (already committed at `ad1f7b9e4`)
- `docs/plans/2026-05-01-tasks-launcher-fab-plan.md` (this file)
