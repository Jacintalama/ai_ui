# Chat Thought Cards + App Builder Icon + Preview Viewport Toggle — Design

**Date:** 2026-05-01
**Branch:** `feat/gdrive-gmail-connectors`
**Files primarily affected:**
- `mcp-servers/tasks/static/preview.html` (sections 1 + 3)
- `mcp-servers/tasks/static/task-panel.js` (section 2)

## Problem

Three small UX gaps on the App Builder + preview surface:

1. **Plain assistant bubbles in the ENHANCE chat panel.** When a user prompts in chat or build mode, the AI reply renders as a plain dark bubble — no visual cue that this is the AI's reasoning, and file edits inside the reply are buried in prose. The reference (image #6) shows a richer "Thought" card with file-edit diff badges that's much easier to scan.
2. **Custom "OI" text icon in the sidebar entry.** The Open WebUI sidebar entry for the App Builder uses a custom-drawn `OI` text glyph that does not match Open WebUI's native icon style — it sticks out next to the briefcase / chat / folder icons of other rows.
3. **No mobile preview.** The preview iframe is always full-width. There is no way to verify how the built app looks at phone sizes without resizing the browser window.

## Goal

- Render assistant replies as a styled "Thought" card; tag inline file-edit lines as green/red diff badges.
- Drop the custom "OI" icon and let the cloned sidebar entry keep Open WebUI's native Workspace SVG.
- Add a `[Desktop] [Phone]` segmented toggle to the preview header that frames the iframe at 390 px in phone mode.

## Non-goals

- No backend SSE / agent changes (no new event types, no markers in `claude_executor.py`).
- No milestone cards, "Ideas to try next" cards, or any other rich agent semantics that don't already exist in the log text.
- No "And so much more" capabilities grid on the App Builder page.
- No persisted viewport preference (resets on page reload — YAGNI).

---

## Section 1 — Chat "Thought" log cards

**Approach.** Pure client-side re-style of existing assistant bubbles in `preview.html`. No backend or SSE schema changes.

**Components.**

- New CSS class `.thought-card` replaces the current assistant-bubble style:
  - Background: existing `var(--surface-2)` (dark card surface)
  - Border: 1 px subtle border matching existing panel chrome
  - Padding: 12 px
  - Above the body: a small uppercase plain-text label `Thought` (no emoji, no leading glyph). 11 px, letter-spacing 0.08 em, muted color.
- Markdown body underneath is unchanged.
- After the assistant reply finishes rendering, a single regex post-process pass scans the rendered body for two patterns and replaces matched text nodes with styled badge spans:
  - Pattern A: `Edited file <path>` (with optional trailing `+N -N` diff stats)
  - Pattern B: `Created file <path>` (same trailing stats)
- Badge styling:
  - `.file-edit-badge { display: inline-flex; gap: 6 px; padding: 2 px 8 px; border-radius: 6 px; background: rgba(255,255,255,0.04); font: 12 px/1.4 monospace; }`
  - `.diff-add { color: #22c55e; }` (`+32`)
  - `.diff-del { color: #ef4444; }` (`-32`)
- User bubbles unchanged.
- Existing streaming "running…" spinner stays; on completion the bubble container picks up `.thought-card` and the post-process runs once.

**Files.** `mcp-servers/tasks/static/preview.html` (CSS rules + small post-process function called from the existing assistant-render path).

---

## Section 2 — App Builder sidebar icon

**Approach.** Remove the custom-icon replacement block; the cloned Workspace row keeps Open WebUI's native SVG. Only the text label rewrite stays.

**Components.**

- Delete the icon-replacement block in `task-panel.js` (currently approx. lines 1144–1165 — the section that builds an `<svg>` containing a `<text>OI</text>` element and calls `cloneIcon.replaceWith(newIcon)`).
- Keep the surrounding logic intact:
  - Row clone (~line 1117)
  - Attribute stripping (`_stripTooltipAttrs`, `data-sveltekit-preload-*`)
  - Tooltip set to `App Builder — create and manage AI-built apps`
  - Label rewrite `Workspace` → `App Builder`
  - Click handler navigates to `/tasks/app-builder`
  - `insertBefore` placement after the Workspace row
- Net diff: ~22 lines removed, 0 added (apart from a one-line comment if the surrounding context needs it).

**Files.** `mcp-servers/tasks/static/task-panel.js`.

---

## Section 3 — Preview viewport toggle

**Approach.** Two-button segmented toggle in the preview header next to the existing Refresh / Open buttons. State is in-memory only (resets per page load).

**Components.**

- DOM: insert a `<div class="viewport-toggle">` containing two buttons before the existing Refresh button:
  - `<button data-viewport="desktop" class="active">Desktop</button>`
  - `<button data-viewport="phone">Phone</button>`
- CSS rules scoped via a `phone-mode` class toggled on `$previewBody`:
  - Default (no class): iframe at 100 % width × 100 % height (current behavior).
  - `.phone-mode` background gets a darker fill to make the framed iframe readable.
  - `.phone-mode iframe` becomes `width: 390 px; max-width: 100 %; height: 100 %; max-height: 844 px; margin: 0 auto; border: 1 px solid var(--border); border-radius: 12 px; display: block;`
- Toggle button styling matches the existing toolbar buttons. Active button has the existing accent / inverted-color treatment used by the chat-mode toggle (`.mode-toggle button.active`).
- One click handler:
  ```js
  $viewportToggle.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-viewport]");
    if (!b) return;
    $viewportToggle.querySelectorAll("button").forEach((x) =>
      x.classList.toggle("active", x === b));
    $previewBody.classList.toggle("phone-mode", b.dataset.viewport === "phone");
  });
  ```
- No JS resize logic; CSS does all width/height work. Refreshing the iframe in phone mode keeps the phone frame.

**Files.** `mcp-servers/tasks/static/preview.html` (CSS rules + DOM addition + click handler, ~40 lines).

---

## Behavior summary

- Open the App Builder via the sidebar — sidebar entry now uses Open WebUI's native Workspace icon, label still reads "App Builder".
- Open a project's preview surface — preview iframe shows in Desktop mode by default; clicking `Phone` reframes it to a centered 390-px-wide device-style frame.
- Send a chat or build prompt — the assistant reply renders as a "Thought" card; any `Edited file <path>` / `Created file <path>` lines (with optional `+N -N`) become inline diff badges.

## Out of scope

- Persisting viewport preference across reloads
- Tablet / custom viewport sizes
- Animating the viewport transition
- Milestone / Ideas-to-try-next cards (would need backend markers)
- Reskinning user bubbles
- Bumping the cache-bust query string in `openwebui-overrides/index.html` — handled in the implementation plan as the final step before deploy.

## Files touched

- `mcp-servers/tasks/static/preview.html` (sections 1 + 3)
- `mcp-servers/tasks/static/task-panel.js` (section 2)
- `openwebui-overrides/index.html` (cache-bust bump only — implementation phase, not a design concern)
