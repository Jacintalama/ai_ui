# Files-tab + Lovable-style Chat Composer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Promote the Files sidebar into a tab, replace the Chat|Build segmented toggle with a Lovable-style `Build ▾ / Plan` dropdown, add a `+` menu with Attach + image-paste + drag-drop in the chat composer, and route image attachments through the `claude` CLI agent's `Read` tool as real vision input. Strip the em-dash from the browser tab title.

**Architecture:** All UI lives in `mcp-servers/tasks/static/preview.html` (single-file static HTML with inline CSS/JS). Backend changes are scoped to `routes_tasks.py` (`/enhance` becomes multipart), `schemas.py` (drop the model from this endpoint, keep it for any other caller), `claude_executor.py` (add `attachments` arg to `build_enhance_prompt`). Image attachments are stored at `apps/<slug>/.attachments/<task_id>/<safe_filename>` and referenced by relative path in the prompt; the agent's `Read` tool reads them as vision input — no Claude SDK swap.

**Tech Stack:** FastAPI + SQLAlchemy async (Python 3.11), pytest + httpx ASGI transport, vanilla JS in a static HTML file, Docker Compose deploy on Hetzner.

**Reference design:** `docs/plans/2026-05-01-files-tab-chat-composer-design.md`

---

## Working agreements

- **Test-first** for all backend changes. UI changes have no automated harness — verify manually via deployment.
- **Frequent commits.** One task = one commit. Commit messages follow project style (see `git log --oneline -20`): `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`, etc.
- **Local pytest** runs from `mcp-servers/tasks/`. Tests use `db_session` fixture from `conftest.py` and an in-memory SQLite. Run a single test: `pytest tests/test_enhance_endpoint.py::test_name -v`. Run module: `pytest tests/test_enhance_endpoint.py -v`.
- **No local Docker.** Deploy to Hetzner via SCP for manual verification (see "Deploy to Hetzner" recipe at the bottom).
- **`data-mode` values stay `"chat"` and `"build"`** internally — only the user-facing label changes (`chat` → `Plan`).

---

## Task 0: Preflight grep — decide §5 Approach A vs B

Determine whether non-browser callers hit `POST /api/tasks/enhance` with JSON. If any exist, we keep both content types (Approach B). If none, we switch to multipart-only (Approach A — simpler).

**Files:** none (read-only)

**Step 1: Search the repo for non-browser callers**

```bash
grep -rn "/api/tasks/enhance\|/enhance" \
  webhook-handler/ n8n-workflows/ scripts/ open-webui-functions/ \
  --include="*.py" --include="*.js" --include="*.json" --include="*.yml" \
  2>/dev/null
```

**Step 2: Decide**

- **Zero non-browser hits** → use **Approach A** (multipart-only) for the rest of the plan. The frontend `apiFetch("POST", "/enhance", {...})` call is the only caller; we'll update it in Task 9.
- **One or more non-browser hits** → switch to **Approach B**. Inspect each caller, decide if it can move to FormData; if not, the `/enhance` handler must accept either content-type. Update Task 6 and Task 7 below to reflect Approach B.

**Step 3: Record the decision**

Append a one-line note to the bottom of this plan file:
```
**Approach decision (Task 0):** A — no non-browser callers found.
```
or
```
**Approach decision (Task 0):** B — found callers in <files>.
```

**Step 4: Commit**

```bash
git add docs/plans/2026-05-01-files-tab-chat-composer-plan.md
git commit -m "docs(plans): record /enhance multipart approach decision"
```

---

## Task 1: Strip em-dash from browser tab title

Trivial fix. Lands the smallest visible change first to confirm the deploy loop works.

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html:6`

**Step 1: Edit the title**

```diff
-  <title>Preview — AIUI Tasks</title>
+  <title>Preview - AIUI Tasks</title>
```

**Step 2: Verify the file**

```bash
grep -n "<title>" mcp-servers/tasks/static/preview.html | head -1
```
Expected: `6:  <title>Preview - AIUI Tasks</title>`

**Step 3: Deploy + manual smoke** (see "Deploy to Hetzner" recipe). Open the live URL, hover the browser tab — title shows `Preview - AIUI Tasks` with a hyphen.

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "style(preview): drop em-dash from browser tab title"
```

---

## Task 2: Files-tab refactor — DOM + JS

Move the file tree from a left aside into a new tab. Tab order: **Code · Files · Supabase · Preview · Structure · Logs · History**.

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (lines ~2114–2129, ~2131, ~2134–2176, ~2994 area, ~CSS block for `.sidebar-files` etc.)

**Step 1: Remove the left aside + its resizer**

Delete:
- `<aside class="sidebar-files" id="sb-files">…</aside>` block (~lines 2114–2129).
- `<div class="resizer" data-resize="files">` sibling (~line 2131).

**Step 2: Add a Files tab button**

In `<nav class="tabs" id="tabs">`, insert between the **Code** tab and the **Supabase** tab (after `data-tab="code"` block, before `data-tab="database"` block):

```html
<button class="tab" data-tab="files">
  <span class="tab-icon">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  </span>
  <span class="tab-label">Files</span>
  <span class="tab-badge" id="badge-files" hidden></span>
</button>
```

**Step 3: Add the Files panel**

In `<div class="panels">`, insert **after** `<div class="panel active" id="panel-code">…</div>` and before `<div class="panel preview-panel" id="panel-preview">`:

```html
<!-- Files panel — file tree + search, full width -->
<div class="panel" id="panel-files">
  <div class="panel-head">
    <span class="filepath">Files</span>
    <div class="panel-actions">
      <span class="count" id="file-count" style="font-size:11px;color:var(--muted);"></span>
    </div>
  </div>
  <div class="panel-body" style="display:flex;flex-direction:column;gap:0;padding:0;">
    <div style="padding:10px 14px;border-bottom:1px solid var(--border);">
      <input class="search-input" id="file-search" type="search"
             placeholder="Search files…" autocomplete="off">
    </div>
    <div class="file-tree" id="file-tree" style="flex:1;overflow:auto;padding:10px;">
      <div class="skeleton skeleton-row" style="width:80%"></div>
      <div class="skeleton skeleton-row" style="width:60%"></div>
      <div class="skeleton skeleton-row" style="width:70%"></div>
      <div class="skeleton skeleton-row" style="width:50%"></div>
    </div>
  </div>
</div>
```

(IDs `file-search`, `file-tree`, `file-count` preserved — existing `loadFileTree()`, search filter, and count-update code keep working byte-identical.)

**Step 4: Wire file-click → switch to Code tab**

Find the file-tree row click handler (search the JS for `loadCode(`). Append after the `loadCode(...)` call:

```js
switchTab('code');
```

(`switchTab` is the existing tab-switcher — search for `data-tab` to confirm the function name; if it's inline, extract it once and call it from both the tab-button delegate and here.)

**Step 5: Update the `/` keyboard shortcut**

Find the global keydown handler that focuses `#file-search` on `/`. Wrap the focus call:

```js
if (e.key === '/' && !isInputFocused()) {
  e.preventDefault();
  switchTab('files');
  setTimeout(() => document.getElementById('file-search')?.focus(), 0);
}
```

**Step 6: Remove the resizer + width state**

- Search for `LS_FILES_WIDTH` (~line 2994) and delete the const + every line that uses it.
- Search for `data-resize="files"` and remove the corresponding `mousedown`/`mousemove`/`mouseup` handlers in the resizer JS.
- In the CSS `<style>` block, delete or comment out:
  - `.sidebar-files`, `.sb-head`, `.sb-title` rules
  - `--sb-files-w` CSS var
  - `.resizer[data-resize="files"]` rule (if it exists)
- **Keep:** any selector that targets `#file-tree`, `#file-search`, `.skeleton`, `.file-tree-row` — those still apply inside the new panel.

**Step 7: Manual verify**

Deploy. Open a project. Confirm:
- Left side has no aside; the workspace stretches full-width up to the right Enhance panel.
- Tab strip shows Code · Files · Supabase · Preview · Structure · Logs · History.
- Click `Files` → tree appears in the panel area.
- Click any file → file content appears in Code panel; tab strip auto-switches to `Code`.
- `/` key from any tab → switches to Files and focuses search.
- Search filters tree.

**Step 8: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): promote Files sidebar into a tab"
```

---

## Task 3: Build / Plan dropdown

Replace the segmented `Chat | Build` toggle with a single `Build ▾` button + popover menu (Build / Plan, with `Alt+P` shortcut). Internal `data-mode` values stay `"chat"` / `"build"`.

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (lines ~2668–2672, CSS area ~1636–1665, JS area ~5438–5470)

**Step 1: Replace the DOM**

Find:
```html
<div class="mode-toggle" id="mode-toggle" role="tablist">
  <button data-mode="chat" class="active" type="button" title="Talk — no code changes">💬 Chat</button>
  <button data-mode="build" type="button" title="Commit an enhancement — runs the build pipeline">Build</button>
</div>
```

Replace with:
```html
<div class="mode-dropdown" id="mode-dropdown">
  <button class="mode-button" id="mode-button" type="button"
          aria-haspopup="menu" aria-expanded="false">
    <span class="mode-label" id="mode-label">Build</span>
    <svg class="caret" width="12" height="12" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="6 9 12 15 18 9"/>
    </svg>
  </button>
  <div class="mode-menu" id="mode-menu" role="menu" hidden>
    <button role="menuitem" data-mode="build" class="active" type="button">
      <span class="title">Build</span>
      <span class="sub">Make changes directly</span>
    </button>
    <button role="menuitem" data-mode="chat" type="button">
      <span class="title">Plan</span>
      <span class="sub">Discuss before building</span>
    </button>
    <div class="menu-foot">Toggle with <kbd>Alt</kbd><kbd>P</kbd></div>
  </div>
</div>
```

**Step 2: Replace the CSS block**

Find the existing `.mode-toggle` rules (~lines 1636–1665) and replace with:

```css
.mode-dropdown { position: relative; }
.mode-button {
  display: inline-flex; align-items: center; gap: 6px;
  height: 28px; padding: 0 10px;
  background: var(--surface-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  font: inherit; font-size: 12px; font-weight: 600;
  cursor: pointer;
}
.mode-button:hover { background: var(--surface-3, var(--surface-2)); }
.mode-button .caret { opacity: 0.7; }
.mode-menu {
  position: absolute; top: calc(100% + 4px); right: 0;
  min-width: 220px; padding: 6px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.18);
  z-index: 30;
}
.mode-menu button[role="menuitem"] {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  width: 100%; padding: 8px 10px;
  background: transparent; border: 0; border-radius: 6px;
  color: var(--text); cursor: pointer; text-align: left;
}
.mode-menu button[role="menuitem"]:hover { background: var(--surface-2); }
.mode-menu button[role="menuitem"].active { background: var(--surface-2); }
.mode-menu .title { font-size: 13px; font-weight: 600; }
.mode-menu .sub { font-size: 11px; color: var(--muted); }
.mode-menu .menu-foot {
  padding: 8px 10px 4px; margin-top: 4px;
  border-top: 1px solid var(--border);
  font-size: 11px; color: var(--muted);
}
.mode-menu .menu-foot kbd {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 3px; padding: 0 4px; font-size: 10px;
  margin: 0 2px;
}
```

**Step 3: Replace the JS handlers**

Find the existing `mode-toggle` handler (search for `const $modeToggle = document.getElementById("mode-toggle");`). Replace its block with:

```js
const $modeBtn = document.getElementById("mode-button");
const $modeMenu = document.getElementById("mode-menu");
const $modeLabel = document.getElementById("mode-label");
let _modeMenuOpen = false;

function openModeMenu() {
  $modeMenu.hidden = false;
  $modeBtn.setAttribute("aria-expanded", "true");
  _modeMenuOpen = true;
  setTimeout(() => document.addEventListener("click", _modeOutsideClick), 0);
  document.addEventListener("keydown", _modeEscClose);
}
function closeModeMenu() {
  $modeMenu.hidden = true;
  $modeBtn.setAttribute("aria-expanded", "false");
  _modeMenuOpen = false;
  document.removeEventListener("click", _modeOutsideClick);
  document.removeEventListener("keydown", _modeEscClose);
}
function _modeOutsideClick(e) {
  if (!document.getElementById("mode-dropdown").contains(e.target)) closeModeMenu();
}
function _modeEscClose(e) { if (e.key === "Escape") closeModeMenu(); }

$modeBtn.addEventListener("click", () => {
  _modeMenuOpen ? closeModeMenu() : openModeMenu();
});
$modeMenu.addEventListener("click", (e) => {
  const item = e.target.closest("button[role='menuitem']");
  if (!item) return;
  const newMode = item.dataset.mode;
  setMode(newMode);
  $modeMenu.querySelectorAll("button[role='menuitem']").forEach(b => {
    b.classList.toggle("active", b.dataset.mode === newMode);
  });
  $modeLabel.textContent = newMode === "build" ? "Build" : "Plan";
  closeModeMenu();
});

// Alt+P toggles modes
document.addEventListener("keydown", (e) => {
  if (!e.altKey || e.key.toLowerCase() !== "p") return;
  if (isInputFocused()) return; // dead-zone in inputs
  e.preventDefault();
  const next = currentMode === "build" ? "chat" : "build";
  setMode(next);
  $modeMenu.querySelectorAll("button[role='menuitem']").forEach(b => {
    b.classList.toggle("active", b.dataset.mode === next);
  });
  $modeLabel.textContent = next === "build" ? "Build" : "Plan";
});
```

(`setMode` and `currentMode` already exist; `isInputFocused` exists if `/` shortcut uses one — if not, define `function isInputFocused(){ const t = document.activeElement; return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable); }` once.)

**Step 4: Manual verify**

Deploy. Confirm:
- Header shows `Build ▾` button (not the segmented two-button).
- Click → menu drops below with Build / Plan rows + Alt+P footer hint.
- Click `Plan` → label flips to `Plan`, send-area placeholder/styling matches today's chat-mode behaviour.
- `Alt+P` toggles back and forth.
- Esc closes the menu. Outside-click closes the menu.
- Sending a message in Plan mode does NOT start a build (matches today's chat behaviour).

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): replace Chat|Build toggle with Build/Plan dropdown"
```

---

## Task 4: Composer — `+` button + Attach popover

Add the `+` icon button and the one-item popover menu. No file logic yet — just the visual and open/close mechanics. Hidden file input + `accept` attribute land in this task.

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (`.enhance-input` block ~lines 2685–2700, CSS area ~1572–1605)

**Step 1: Replace the `.enhance-input` markup**

Find:
```html
<div class="enhance-input">
  <div class="reply-banner" id="reply-banner">…</div>
  <textarea id="enhance-prompt" placeholder="Type what you want to change…" maxlength="2000" rows="3"></textarea>
  <div class="row">
    <span class="warn" id="enhance-warn"></span>
    <button class="btn btn-primary" id="enhance-send">Send</button>
  </div>
</div>
```

Replace with:
```html
<div class="enhance-input">
  <div class="reply-banner" id="reply-banner">
    <span class="arrow">↩</span>
    <span class="label"><strong>Replying</strong> to the AI's question</span>
    <button class="clear" id="reply-clear" title="Cancel reply (send as new enhancement)" type="button">×</button>
  </div>

  <div class="attachment-strip" id="attachment-strip" hidden></div>

  <textarea id="enhance-prompt" placeholder="Type what you want to change…"
            maxlength="2000" rows="3"></textarea>

  <div class="row">
    <div class="row-left">
      <div class="plus-dropdown" id="plus-dropdown">
        <button class="icon-btn plus-btn" id="plus-btn" type="button"
                aria-haspopup="menu" aria-expanded="false" title="Add">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
        <div class="plus-menu" id="plus-menu" role="menu" hidden>
          <button role="menuitem" id="plus-attach" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
            <span>Attach</span>
          </button>
        </div>
        <input type="file" id="attach-input" multiple
               accept="image/png,image/jpeg,image/webp,image/gif" hidden>
      </div>
    </div>
    <span class="warn" id="enhance-warn"></span>
    <button class="btn btn-primary" id="enhance-send">Send</button>
  </div>
</div>
```

**Step 2: Add CSS**

After the existing `.enhance-input` rules in the `<style>` block, append:

```css
.enhance-input .row { display: flex; align-items: center; gap: 8px; }
.enhance-input .row-left { display: flex; align-items: center; gap: 6px; flex: 1; }
.plus-dropdown { position: relative; }
.plus-btn {
  width: 28px; height: 28px; border-radius: 6px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--surface-2); color: var(--text);
  border: 1px solid var(--border); cursor: pointer;
}
.plus-btn:hover { background: var(--surface-3, var(--surface-2)); }
.plus-menu {
  position: absolute; bottom: calc(100% + 4px); left: 0;
  min-width: 160px; padding: 6px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.18);
  z-index: 30;
}
.plus-menu button[role="menuitem"] {
  display: flex; align-items: center; gap: 8px;
  width: 100%; padding: 8px 10px;
  background: transparent; border: 0; border-radius: 6px;
  color: var(--text); cursor: pointer; font-size: 13px; text-align: left;
}
.plus-menu button[role="menuitem"]:hover { background: var(--surface-2); }
```

**Step 3: Add open/close JS**

Append to the IIFE near the existing mode-dropdown code:

```js
const $plusBtn = document.getElementById("plus-btn");
const $plusMenu = document.getElementById("plus-menu");
let _plusMenuOpen = false;

function openPlusMenu() {
  $plusMenu.hidden = false;
  $plusBtn.setAttribute("aria-expanded", "true");
  _plusMenuOpen = true;
  setTimeout(() => document.addEventListener("click", _plusOutsideClick), 0);
  document.addEventListener("keydown", _plusEscClose);
}
function closePlusMenu() {
  $plusMenu.hidden = true;
  $plusBtn.setAttribute("aria-expanded", "false");
  _plusMenuOpen = false;
  document.removeEventListener("click", _plusOutsideClick);
  document.removeEventListener("keydown", _plusEscClose);
}
function _plusOutsideClick(e) {
  if (!document.getElementById("plus-dropdown").contains(e.target)) closePlusMenu();
}
function _plusEscClose(e) { if (e.key === "Escape") closePlusMenu(); }

$plusBtn.addEventListener("click", () => {
  _plusMenuOpen ? closePlusMenu() : openPlusMenu();
});
document.getElementById("plus-attach").addEventListener("click", () => {
  closePlusMenu();
  document.getElementById("attach-input").click();
});
```

**Step 4: Manual verify**

Deploy. Confirm:
- Composer shows `+` button at the bottom-left of the input row, before the `Send` button.
- Click `+` → menu opens upward with one row: `Attach` + paperclip icon.
- Click `Attach` → native file picker opens with image-only filter.
- Esc closes the menu. Outside-click closes the menu.
- (Selecting a file in the picker does nothing yet — wired up in Task 5.)

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): add + button + Attach popover to composer"
```

---

## Task 5: Attachment chips — file-input + paste + drag-drop, with validation

Wire the attach-input change handler, paste-on-textarea handler, and drag-drop on textarea to populate `pendingAttachments`. Render chips with thumbnails. Implement client-side validation (MIME, size, count). Send button does NOT yet upload — that's Task 9.

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (CSS + JS)

**Step 1: CSS for `.attachment-strip` and `.attachment-chip`**

Append to `<style>`:

```css
.attachment-strip {
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
  margin-bottom: 6px;
}
.attachment-chip {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  padding: 4px 28px 4px 4px;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 8px;
  max-width: 200px;
}
.attachment-chip .thumb {
  width: 40px; height: 40px;
  object-fit: cover; border-radius: 4px; flex: 0 0 auto;
}
.attachment-chip .meta {
  display: flex; flex-direction: column; gap: 0; min-width: 0;
}
.attachment-chip .name {
  font-size: 12px; font-weight: 600; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 120px;
}
.attachment-chip .size { font-size: 10px; color: var(--muted); }
.attachment-chip .remove {
  position: absolute; top: 2px; right: 2px;
  width: 18px; height: 18px; border: 0; border-radius: 50%;
  background: var(--surface); color: var(--muted);
  cursor: pointer; font-size: 12px; line-height: 1;
  display: flex; align-items: center; justify-content: center;
}
.attachment-chip .remove:hover { color: var(--text); background: var(--surface-3, var(--surface-2)); }
#enhance-prompt.drag-over { outline: 2px dashed var(--accent); outline-offset: -4px; }
```

**Step 2: JS — state + helpers**

Append to the IIFE (near the plus-menu code):

```js
const ALLOWED_MIME = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_FILES = 5;

let pendingAttachments = []; // { id, file, previewUrl }

const $strip = document.getElementById("attachment-strip");
const $attachInput = document.getElementById("attach-input");
const $promptTa = document.getElementById("enhance-prompt");

function _humanKB(n) { return (n / 1024).toFixed(0) + " KB"; }

function _renderChips() {
  if (pendingAttachments.length === 0) {
    $strip.hidden = true; $strip.innerHTML = ""; return;
  }
  $strip.hidden = false;
  $strip.innerHTML = "";
  for (const a of pendingAttachments) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    chip.innerHTML =
      '<img class="thumb" src="' + a.previewUrl + '" alt="">' +
      '<div class="meta">' +
        '<span class="name" title="' + a.file.name.replace(/"/g,'&quot;') + '">' +
          a.file.name + '</span>' +
        '<span class="size">' + _humanKB(a.file.size) + '</span>' +
      '</div>' +
      '<button class="remove" type="button" title="Remove" data-id="' + a.id + '">×</button>';
    $strip.appendChild(chip);
  }
}

$strip.addEventListener("click", (e) => {
  const btn = e.target.closest(".remove");
  if (!btn) return;
  const id = btn.dataset.id;
  const idx = pendingAttachments.findIndex(a => a.id === id);
  if (idx >= 0) {
    URL.revokeObjectURL(pendingAttachments[idx].previewUrl);
    pendingAttachments.splice(idx, 1);
    _renderChips();
  }
});

function addFiles(fileList) {
  for (const f of fileList) {
    if (!ALLOWED_MIME.has(f.type)) {
      toast("Only PNG / JPEG / WebP / GIF images are supported.", "error", 4000);
      continue;
    }
    if (f.size > MAX_FILE_BYTES) {
      toast(f.name + " is too large (max 5 MB).", "error", 4000);
      continue;
    }
    if (pendingAttachments.length >= MAX_FILES) {
      toast("Up to " + MAX_FILES + " attachments per message.", "error", 4000);
      break;
    }
    pendingAttachments.push({
      id: "att_" + Math.random().toString(36).slice(2, 10),
      file: f,
      previewUrl: URL.createObjectURL(f),
    });
  }
  _renderChips();
}

function clearPendingAttachments() {
  for (const a of pendingAttachments) URL.revokeObjectURL(a.previewUrl);
  pendingAttachments = [];
  _renderChips();
}

// File-picker change
$attachInput.addEventListener("change", () => {
  if ($attachInput.files && $attachInput.files.length) addFiles($attachInput.files);
  $attachInput.value = ""; // allow same-file reselect
});

// Paste image into textarea
$promptTa.addEventListener("paste", (e) => {
  if (!e.clipboardData) return;
  const files = [];
  for (const item of e.clipboardData.items) {
    if (item.kind === "file" && item.type.startsWith("image/")) {
      const f = item.getAsFile();
      if (f) files.push(f);
    }
  }
  if (files.length) {
    e.preventDefault(); // don't paste the binary as text
    addFiles(files);
  }
});

// Drag-drop image onto textarea
$promptTa.addEventListener("dragover", (e) => {
  if (e.dataTransfer && Array.from(e.dataTransfer.items).some(i => i.kind === "file")) {
    e.preventDefault();
    $promptTa.classList.add("drag-over");
  }
});
$promptTa.addEventListener("dragleave", () => $promptTa.classList.remove("drag-over"));
$promptTa.addEventListener("drop", (e) => {
  $promptTa.classList.remove("drag-over");
  if (!e.dataTransfer || !e.dataTransfer.files.length) return;
  e.preventDefault();
  addFiles(e.dataTransfer.files);
});
```

**Step 3: Manual verify**

Deploy. Confirm:
- Click `+ → Attach` → pick a PNG → chip appears with thumbnail + name + size + ×.
- Click × → chip disappears.
- Pick 6 PNGs at once → first 5 land as chips, toast says "Up to 5 attachments per message."
- Pick a `.pdf` → toast rejects MIME, no chip.
- Pick a 10 MB image (any large image) → toast rejects size.
- Use Win+Shift+S to capture screenshot, Ctrl+V into the textarea → chip appears, **textarea text is unchanged** (no binary pasted as garbage).
- Drag an image file from desktop onto the textarea → chip appears.
- Send button: does whatever it does today (text-only path is wired in Task 9).

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): wire chip render + paste/drop/picker for image attachments"
```

---

## Task 6: Backend — `_safe_filename` + magic-byte sniff helpers (TDD)

Pure helpers in `routes_tasks.py` — no FastAPI, no DB. Test in isolation first.

**Files:**
- Create: `mcp-servers/tasks/tests/test_attachment_helpers.py`
- Modify: `mcp-servers/tasks/routes_tasks.py` (add helpers near top of file, after imports)

**Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_attachment_helpers.py`:

```python
"""Tests for attachment helpers in routes_tasks.

These run pure-Python — no DB, no app. Just helpers."""
import pytest


def test_safe_filename_strips_path_components():
    from routes_tasks import _safe_filename
    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename("/abs/path/file.png") == "file.png"
    assert _safe_filename("C:\\Windows\\file.png") == "file.png"


def test_safe_filename_keeps_extension():
    from routes_tasks import _safe_filename
    assert _safe_filename("screenshot.png") == "screenshot.png"


def test_safe_filename_rejects_empty_and_dotfiles():
    from routes_tasks import _safe_filename
    assert _safe_filename("") == "unnamed"
    assert _safe_filename("...") == "unnamed"
    # Dotfile-ish: no stem, only extension
    assert _safe_filename(".hidden") == "unnamed.hidden" or _safe_filename(".hidden") == "hidden"


def test_safe_filename_collapses_dangerous_chars():
    from routes_tasks import _safe_filename
    out = _safe_filename("hello world!@#$.png")
    assert out.endswith(".png")
    assert "/" not in out and "\\" not in out and ".." not in out


def test_sniff_image_mime_png():
    from routes_tasks import _sniff_image_mime
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    assert _sniff_image_mime(png) == "image/png"


def test_sniff_image_mime_jpeg():
    from routes_tasks import _sniff_image_mime
    assert _sniff_image_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg"


def test_sniff_image_mime_webp():
    from routes_tasks import _sniff_image_mime
    riff = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 4
    assert _sniff_image_mime(riff) == "image/webp"


def test_sniff_image_mime_gif():
    from routes_tasks import _sniff_image_mime
    assert _sniff_image_mime(b"GIF89a" + b"\x00" * 6) == "image/gif"
    assert _sniff_image_mime(b"GIF87a" + b"\x00" * 6) == "image/gif"


def test_sniff_image_mime_rejects_other():
    from routes_tasks import _sniff_image_mime
    assert _sniff_image_mime(b"%PDF-1.4" + b"\x00" * 4) is None
    assert _sniff_image_mime(b"\x00" * 12) is None
```

**Step 2: Run to confirm they fail**

```bash
cd mcp-servers/tasks && pytest tests/test_attachment_helpers.py -v
```
Expected: ImportError or AttributeError on `_safe_filename` / `_sniff_image_mime`.

**Step 3: Implement the helpers**

In `mcp-servers/tasks/routes_tasks.py`, after the import block (find a good spot — near other module-level helpers; if none, just before the first `@router` decorator), add:

```python
import re as _re
from pathlib import PurePath as _PurePath

_FILENAME_SAFE_RE = _re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    """Strip path components and dangerous characters from an uploaded filename.

    Returns 'unnamed' (or 'unnamed.<ext>') when nothing usable remains.
    Never raises.
    """
    if not name:
        return "unnamed"
    base = _PurePath(name.replace("\\", "/")).name
    if not base or set(base) <= {"."}:
        return "unnamed"
    # Collapse runs of unsafe chars to a single underscore
    cleaned = _FILENAME_SAFE_RE.sub("_", base).strip("._")
    if not cleaned:
        # Salvage extension if any
        if "." in base:
            ext = base.rsplit(".", 1)[-1]
            ext = _FILENAME_SAFE_RE.sub("", ext)
            return ("unnamed." + ext) if ext else "unnamed"
        return "unnamed"
    return cleaned


_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff",      "image/jpeg"),
    (b"GIF87a",            "image/gif"),
    (b"GIF89a",            "image/gif"),
)


def _sniff_image_mime(head: bytes) -> str | None:
    """Return canonical MIME for the first 12 bytes of an image, or None.

    Recognises PNG, JPEG, GIF, WebP. Used as a server-side defence against
    a client that lies about Content-Type.
    """
    for sig, mime in _IMAGE_SIGNATURES:
        if head.startswith(sig):
            return mime
    # WebP: RIFF....WEBP
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None
```

**Step 4: Run tests — should pass**

```bash
cd mcp-servers/tasks && pytest tests/test_attachment_helpers.py -v
```
Expected: 9 passing.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/tests/test_attachment_helpers.py mcp-servers/tasks/routes_tasks.py
git commit -m "feat(tasks): add _safe_filename + _sniff_image_mime helpers"
```

---

## Task 7: Backend — convert `/enhance` to multipart (TDD)

Endpoint signature change. Existing tests in `test_enhance_endpoint.py` that POST `json={...}` must move to `data={...}` (FormData) — those tests guide the implementation. Add new tests for attachment validation.

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py` (the `enhance` handler ~lines 623–718)
- Modify: `mcp-servers/tasks/tests/test_enhance_endpoint.py` (every test that POSTs to `/enhance`)
- Create: new tests in the same file for attachment paths

**Step 1: Migrate existing tests from JSON to FormData (will fail until handler changes)**

Find every `r = await c.post("/api/tasks/enhance", headers=..., json={...})` in `test_enhance_endpoint.py` and change to:

```python
r = await c.post(
    "/api/tasks/enhance",
    headers=ADMIN_HEADERS,
    data={"source_task_id": str(...), "prompt": "..."},
)
```

(`httpx`'s `data=` sends as `application/x-www-form-urlencoded`, which FastAPI's `Form(...)` accepts identically to multipart for non-file fields.)

**Step 2: Add new attachment tests**

Append to `test_enhance_endpoint.py`:

```python
async def test_enhance_accepts_multipart_with_image(db_session, tmp_path, monkeypatch):
    """Image attached → file written to apps/<slug>/.attachments/<task_id>/<safe_name>."""
    import os
    monkeypatch.setenv("APPS_DIR", str(tmp_path))  # if your code reads APPS_DIR; else use config
    source = _make_task()
    db_session.add(source); await db_session.commit(); await db_session.refresh(source)

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            data={"source_task_id": str(source.id), "prompt": "see attached"},
            files=[("files", ("shot.png", png_bytes, "image/png"))],
        )
    assert r.status_code == 202, r.text
    new_id = r.json()["id"]
    expected = tmp_path / "meeting-notes" / ".attachments" / new_id / "shot.png"
    assert expected.exists()
    assert expected.read_bytes() == png_bytes


async def test_enhance_rejects_non_image_mime(db_session):
    source = _make_task()
    db_session.add(source); await db_session.commit(); await db_session.refresh(source)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            data={"source_task_id": str(source.id), "prompt": "x"},
            files=[("files", ("doc.pdf", b"%PDF-1.4\n", "application/pdf"))],
        )
    assert r.status_code == 400
    assert "supported" in r.json()["detail"].lower() or "image" in r.json()["detail"].lower()


async def test_enhance_rejects_too_many_files(db_session):
    source = _make_task()
    db_session.add(source); await db_session.commit(); await db_session.refresh(source)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    files = [("files", (f"f{i}.png", png, "image/png")) for i in range(6)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            data={"source_task_id": str(source.id), "prompt": "x"},
            files=files,
        )
    assert r.status_code == 400
    assert "max 5" in r.json()["detail"] or "5" in r.json()["detail"]


async def test_enhance_rejects_oversized_file(db_session):
    source = _make_task()
    db_session.add(source); await db_session.commit(); await db_session.refresh(source)
    big = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (5 * 1024 * 1024 + 1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            data={"source_task_id": str(source.id), "prompt": "x"},
            files=[("files", ("big.png", big, "image/png"))],
        )
    assert r.status_code == 400
    assert "5" in r.json()["detail"] or "large" in r.json()["detail"].lower()


async def test_enhance_rejects_lying_content_type(db_session):
    """Magic-byte sniff catches a pdf masquerading as image/png."""
    source = _make_task()
    db_session.add(source); await db_session.commit(); await db_session.refresh(source)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks/enhance",
            headers=ADMIN_HEADERS,
            data={"source_task_id": str(source.id), "prompt": "x"},
            files=[("files", ("evil.png", b"%PDF-1.4\n" + b"\x00" * 16, "image/png"))],
        )
    assert r.status_code == 400
```

**Step 3: Run — confirm they fail**

```bash
cd mcp-servers/tasks && pytest tests/test_enhance_endpoint.py -v
```
Expected: every test fails (handler still expects JSON `body`).

**Step 4: Implement the new handler**

In `mcp-servers/tasks/routes_tasks.py`, replace the `enhance` handler. Keep the existing concurrency / role checks; only the input parsing and a new "save attachments" block change.

```python
from fastapi import File, Form, UploadFile

ALLOWED_MIME: set[str] = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 5


@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(
    source_task_id: UUID = Form(...),
    prompt: str = Form(..., min_length=1, max_length=2000),
    files: list[UploadFile] = File(default_factory=list),
    user: AdminUser = Depends(current_admin),
):
    """Create a new BUILD task that modifies an existing app, optionally with image attachments."""
    import asyncio
    from claude_executor import build_enhance_prompt
    from models import TaskExecution
    from routes_execution import _run_execution, _RUNNING, _lookup_supabase_config

    # ── Reject too many files BEFORE touching the DB ──
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Too many attachments (max {MAX_FILES})")

    # ── Read+validate each file fully into memory (≤ 5 MB × 5 = 25 MB worst case) ──
    validated: list[tuple[str, bytes]] = []  # [(safe_name, body)]
    for f in files:
        body = await f.read(MAX_FILE_BYTES + 1)
        if len(body) > MAX_FILE_BYTES:
            raise HTTPException(400, f"{f.filename}: file too large (max 5 MB)")
        if f.content_type not in ALLOWED_MIME:
            raise HTTPException(400, f"Unsupported file type: {f.content_type}. Images only (PNG, JPEG, WebP, GIF).")
        if _sniff_image_mime(body[:12]) is None:
            raise HTTPException(400, f"{f.filename}: file contents do not match a supported image format.")
        validated.append((_safe_filename(f.filename or "image"), body))

    async with session() as s:
        # 1. Validate source (unchanged from old handler)
        source = (await s.execute(
            select(TaskItem).where(TaskItem.id == source_task_id)
        )).scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=404, detail="Source task not found")
        if source.action_type != "BUILD":
            raise HTTPException(status_code=400, detail="Can only enhance BUILD tasks")
        if not source.built_app_slug:
            raise HTTPException(
                status_code=400,
                detail="Source task has no built_app_slug — nothing to enhance",
            )

        from routes_projects import _require_role
        await _require_role(s, source.built_app_slug, user.email, "editor",
                            is_admin=user.is_admin)

        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"build:{source.built_app_slug}"},
        )
        in_flight = (await s.execute(
            select(TaskItem).where(
                TaskItem.built_app_slug == source.built_app_slug,
                TaskItem.status.in_(["running", "planning", "awaiting_input"]),
            )
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(
                status_code=409,
                detail=f"Another enhancement is already in progress for apps/{source.built_app_slug}/",
            )

        new_task = TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name=user.email.split("@")[0],
            assignee_email=user.email,
            description=f"Enhance apps/{source.built_app_slug}/: {prompt.strip()[:400]}",
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=max(source.max_attempts or 1, 1),
            built_app_slug=source.built_app_slug,
            plan_status="approved",
        )
        s.add(new_task)
        await s.commit()
        await s.refresh(new_task)

        execution = TaskExecution(task_id=new_task.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(execution)
        supabase_url, has_db_uri = await _lookup_supabase_config(s, source.built_app_slug)

    # ── Persist attachments to disk now that we have new_task.id ──
    attachment_rel_paths: list[str] = []
    if validated:
        from pathlib import Path
        import os
        apps_dir = Path(os.environ.get("APPS_DIR", "apps"))
        att_dir = apps_dir / source.built_app_slug / ".attachments" / str(new_task.id)
        att_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        for original_safe, body in validated:
            name = original_safe
            i = 1
            while name in used_names or (att_dir / name).exists():
                stem, _, ext = original_safe.rpartition(".")
                stem = stem or original_safe
                name = f"{stem}_{i}.{ext}" if ext and ext != original_safe else f"{original_safe}_{i}"
                i += 1
            (att_dir / name).write_bytes(body)
            used_names.add(name)
            attachment_rel_paths.append(f".attachments/{new_task.id}/{name}")

    prompt_text = build_enhance_prompt(
        slug=source.built_app_slug,
        user_request=prompt.strip(),
        attempt_count=0,
        max_attempts=new_task.max_attempts,
        supabase_url=supabase_url,
        has_db_uri=has_db_uri,
        user_email=user.email,
        attachments=attachment_rel_paths or None,
    )
    _RUNNING[new_task.id] = {"task": None, "proc": None}
    bg = asyncio.create_task(_run_execution(new_task.id, execution.id, prompt_text))
    _RUNNING[new_task.id]["task"] = bg

    return new_task
```

**Step 5: Run all enhance tests**

```bash
cd mcp-servers/tasks && pytest tests/test_enhance_endpoint.py tests/test_attachment_helpers.py -v
```
Expected: every test passes.

**Step 6: Run the broader test suite to catch regressions**

```bash
cd mcp-servers/tasks && pytest tests/ -v --tb=short
```
Expected: every test passes. (`test_enhance_prompt.py` may need a tweak if it hard-asserts the attachments-stanza absence; if it just asserts `EnhanceRequest` schema validation, it's unrelated and stays green.)

**Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py mcp-servers/tasks/tests/test_enhance_endpoint.py
git commit -m "feat(tasks): /enhance accepts multipart + image attachments"
```

---

## Task 8: Backend — `build_enhance_prompt(attachments=...)` (TDD)

Add the optional `attachments` kw-arg and the prompt stanza.

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` (find `def build_enhance_prompt`)
- Modify: `mcp-servers/tasks/tests/test_enhance_prompt.py` (add cases)

**Step 1: Write failing tests**

Append to `tests/test_enhance_prompt.py`:

```python
def test_build_enhance_prompt_no_attachments_omits_stanza():
    from claude_executor import build_enhance_prompt
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="add a header",
        attempt_count=0,
        max_attempts=3,
        supabase_url=None,
        has_db_uri=False,
        user_email="r@x.com",
    )
    assert "Attached images" not in out


def test_build_enhance_prompt_with_attachments_includes_stanza():
    from claude_executor import build_enhance_prompt
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="match this layout",
        attempt_count=0,
        max_attempts=3,
        supabase_url=None,
        has_db_uri=False,
        user_email="r@x.com",
        attachments=[".attachments/abc-123/shot.png", ".attachments/abc-123/mockup.jpg"],
    )
    assert "Attached images" in out
    assert "Read them with your Read tool" in out
    assert ".attachments/abc-123/shot.png" in out
    assert ".attachments/abc-123/mockup.jpg" in out
```

**Step 2: Run — confirm fail**

```bash
cd mcp-servers/tasks && pytest tests/test_enhance_prompt.py -v
```
Expected: `test_build_enhance_prompt_with_attachments_includes_stanza` fails (TypeError: unexpected kwarg `attachments`).

**Step 3: Implement**

In `claude_executor.py`, find `def build_enhance_prompt(...)` and:
- Add `attachments: list[str] | None = None` to the signature.
- Just before `return` (after the prompt body is fully composed), insert:

```python
if attachments:
    body += (
        "\n\n## Attached images\n"
        "The user attached these images. Read them with your Read tool "
        "before responding — the user is referencing them in the request. "
        "If a file can't be read, tell the user which one:\n"
    )
    for rel in attachments:
        body += f"- {rel}\n"
```

(The exact local variable name might be `prompt`, `out`, or string-built differently — adapt to whatever the function actually uses to accumulate text. The stanza itself goes at the end.)

**Step 4: Run — confirm pass**

```bash
cd mcp-servers/tasks && pytest tests/test_enhance_prompt.py -v
```
Expected: all green.

**Step 5: Run the full task suite**

```bash
cd mcp-servers/tasks && pytest tests/ -v --tb=short
```

**Step 6: Commit**

```bash
git add mcp-servers/tasks/claude_executor.py mcp-servers/tasks/tests/test_enhance_prompt.py
git commit -m "feat(prompts): build_enhance_prompt accepts attachments arg"
```

---

## Task 9: Frontend — wire FormData send path

Change the existing `apiFetch("POST", "/enhance", {...})` call to send `FormData` whenever attachments exist; keep the JSON-equivalent (now form fields) when none.

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (around line 6027)

**Step 1: Add a multipart helper next to `apiFetch`**

Just below the existing `apiFetch` (~line 3215), add:

```js
async function apiFetchMultipart(method, path, formData) {
  const r = await fetch(API_BASE + path, {
    method,
    credentials: "include",
    headers: authHeaders(), // do NOT set Content-Type — browser sets boundary
    body: formData,
  });
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText);
    const err = new Error(r.status + " " + text);
    err.status = r.status;
    throw err;
  }
  return r.json();
}
```

**Step 2: Replace the existing `/enhance` call**

Find (~line 6027):
```js
const resp = await apiFetch("POST", "/enhance", {
  source_task_id: taskId,
  prompt: text,
});
```

Replace with:
```js
const fd = new FormData();
fd.append("source_task_id", taskId);
fd.append("prompt", text);
for (const a of pendingAttachments) {
  fd.append("files", a.file, a.file.name);
}
const resp = await apiFetchMultipart("POST", "/enhance", fd);
clearPendingAttachments(); // succeed or fail, drop them after the request fires
```

(Move the `clearPendingAttachments` to a `finally` block if you'd rather keep them on error so the user can retry — design says clear after request fires, but a `finally` is the pragmatic spot. Either is fine; pick one.)

**Step 3: Manual end-to-end smoke**

Deploy. Open a project with a built app. In the Enhance panel:

1. **No attachment** — type "add a footer" → Send. Behaviour identical to today (status 202, build runs, log streams). Verify network tab shows `multipart/form-data` body with two text parts (`source_task_id`, `prompt`), zero file parts.
2. **With one image** — paste a screenshot, type "match this style", Send. Watch the agent log on the right — you should see the agent invoke its `Read` tool on `.attachments/<task-id>/...png` and reference the image's content in its reply.
3. **SSH into the server** and check the file actually landed:
   ```bash
   ssh root@46.224.193.25 "ls -la /root/proxy-server/apps/<slug>/.attachments/"
   ```
   (If the `tasks` container mounts `apps/` from the host, that's the path; otherwise, check inside the container with `docker exec`.)

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(preview): send /enhance as multipart with image attachments"
```

---

## Task 10: Add `.attachments/` to per-app `.gitignore`

The executor commits app changes to git on each successful build. Without a gitignore entry, attachment blobs land in the build's commit history.

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` (find where the app's `.gitignore` is written or seeded — search for `.gitignore` literal)

**Step 1: Find the gitignore write site**

```bash
grep -n "\.gitignore" mcp-servers/tasks/claude_executor.py mcp-servers/tasks/templates.py
```

**Step 2: Make it idempotent — add the line if missing**

Wherever the per-app `.gitignore` is created or updated, ensure `.attachments/` is appended. Pattern:

```python
gitignore_path = app_dir / ".gitignore"
existing = gitignore_path.read_text() if gitignore_path.exists() else ""
if ".attachments/" not in existing.splitlines():
    with gitignore_path.open("a") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(".attachments/\n")
```

**Step 3: Add a test** (or find an existing template test and extend it)

If `test_template_app_copy.py` already verifies the gitignore template content, add an assertion that `.attachments/` is in it. Otherwise add a small dedicated test:

```python
async def test_gitignore_excludes_attachments(tmp_path, monkeypatch):
    # ... seed a fresh app dir as the executor would, run the gitignore step,
    # then assert '.attachments/' is in (app_dir / '.gitignore').read_text().
```

**Step 4: Run, verify, commit**

```bash
cd mcp-servers/tasks && pytest tests/test_template_app_copy.py -v
git add mcp-servers/tasks/claude_executor.py mcp-servers/tasks/tests/<test_file>.py
git commit -m "fix(tasks): gitignore .attachments/ in per-app repos"
```

---

## Task 11: Final manual verification + cache-bust

Walk the full test plan from §6 of the design doc against the live deploy.

**Files:** none

**Step 1: Deploy** (see recipe below).

**Step 2: Hard-reload** the App Builder URL in your browser (Ctrl+Shift+R) to bypass any cached JS/HTML.

**Step 3: Walk all 7 verification scenarios**

1. Files-tab: tree visible, search filters, file-click switches to Code, `/` shortcut.
2. Build/Plan dropdown: menu, Alt+P, Esc/outside-click close, Plan-mode no build.
3. Composer +: menu opens upward, Attach picker, validation toasts (MIME, size, count).
4. Paste/drop: screenshot Ctrl+V, desktop drag, both produce chips.
5. Send with attachment: `multipart/form-data` request, file at `apps/<slug>/.attachments/<task_id>/`, agent Read tool fires, reply references image.
6. Send without attachment: regression-clean, identical to today.
7. Tab title: `Preview - AIUI Tasks` (hyphen, no em-dash).

**Step 4: If anything fails**, file a follow-up task; **don't** sign this off until each scenario passes.

**Step 5: Final commit (if any tweaks were made)**

If pure verification with no code changes, skip the commit — task is "verify and report."

---

## Deploy to Hetzner (recipe — you'll use this between tasks for manual verify)

```bash
# From repo root, push static + Python to the server
scp mcp-servers/tasks/static/preview.html \
    root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/preview.html

scp mcp-servers/tasks/routes_tasks.py \
    mcp-servers/tasks/claude_executor.py \
    mcp-servers/tasks/schemas.py \
    root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/

# Rebuild + restart the tasks service
ssh root@46.224.193.25 \
  "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

Static-only changes (preview.html alone) usually don't need a rebuild — just `scp` the file and the volume-mounted static dir picks it up. If unsure, rebuild.

---

## Out of scope (follow-ups, file as separate plan)

- `.attachments/` janitor cron + Grafana disk panel.
- Text-file attachments (full Approach 2 — adds .txt/.md/.json/.csv inlining).
- Drag-to-reorder tabs.
- Multi-thread chat history per project (the original "History" menu item was cut).

---

**Approach decision (Task 0):** A — no non-browser callers found. Only doc references and the test suite (which Task 7 already updates).

**Task 1 status:** already done in commit `12fc2b354` (`<title>` is now `Preview` — no em-dash). Skip during execution.

