# Chat Thought Cards + App Builder Icon + Preview Viewport Toggle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restyle assistant replies as "Thought" cards with file-edit diff badges, drop the custom "OI" sidebar icon, and add a Desktop / Phone preview viewport toggle.

**Architecture:** Three independent client-side changes scoped to two existing files (`preview.html`, `task-panel.js`). No backend changes, no SSE schema changes, no new dependencies. Each section is independently shippable.

**Tech Stack:** Vanilla JS + CSS injected into the existing tasks service static HTML (`mcp-servers/tasks/static/`). Tested via grep checks + manual browser verification. No unit-test framework wired into these static files (pre-existing convention; the `tests/` directory only exercises Python backend).

**Reference design:** `docs/plans/2026-05-01-chat-thought-icon-viewport-design.md`

---

## Section 1 — Chat "Thought" log cards

### Task 1: Add `.thought-card` CSS for both bubble surfaces

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` (insert after the existing `.enhance-bubble.ai .cancel-action:hover` rule near line 1488; this is the natural end of the assistant-bubble CSS block before `.enhance-empty` begins at line 1490)

**Step 1: Read current state**

Run:
```bash
sed -n '1488,1492p' mcp-servers/tasks/static/preview.html
```
Expected output (verbatim):
```
    .enhance-bubble.ai .cancel-action:hover {
      background: var(--danger-soft);
    }
    .enhance-bubble.ai.done .cancel-action,
    .enhance-bubble.ai.failed .cancel-action { display: none; }
```

**Step 2: Insert the new CSS block immediately after line 1488 (the `:hover` closing brace) and before the `.done .cancel-action` rule**

Insert these rules:

```css
    /* Thought card — wraps every assistant reply (build + chat panes). */
    .enhance-bubble.ai .body,
    .chat-bubble.ai .body {
      position: relative;
    }
    .enhance-bubble.ai .body::before,
    .chat-bubble.ai .body::before {
      content: "Thought";
      display: block;
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 8px;
    }
    /* Suppress the label while we're still streaming / waiting. */
    .enhance-bubble.ai:not(.done):not(.failed) .body::before,
    .chat-bubble.thinking .body::before { content: none; }

    /* Inline file-edit badge produced by applyFileEditBadges() below. */
    .file-edit-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 8px;
      margin: 2px 4px 2px 0;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      font-family: var(--font-mono);
      font-size: 11.5px;
      color: var(--text-2);
      line-height: 1.4;
    }
    .file-edit-badge .verb {
      color: var(--muted);
      font-family: inherit;
      font-size: 10.5px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .file-edit-badge .path { color: var(--text); }
    .file-edit-badge .diff-add { color: #22c55e; }
    .file-edit-badge .diff-del { color: #ef4444; }
```

**Step 3: Verify the rules landed**

Run:
```bash
grep -c "Thought card — wraps every assistant reply" mcp-servers/tasks/static/preview.html
grep -c "file-edit-badge" mcp-servers/tasks/static/preview.html
```
Expected: `1` and `≥ 6` (one rule definition + multiple selectors).

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
style(preview): add thought-card label + file-edit badge CSS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `applyFileEditBadges()` post-process helper

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — insert near the existing helpers, just **before** `function renderBubble` at line 5367

**Step 1: Read current state**

Run:
```bash
sed -n '5365,5370p' mcp-servers/tasks/static/preview.html
```
Expected (note: line 5366 is the blank line before `renderBubble`):
```

  function renderBubble(kind, content, opts) {
```

**Step 2: Insert helper before `renderBubble`**

Insert these lines so they appear immediately before `function renderBubble`:

```javascript
  // Replace plain "Edited file <path>" / "Created file <path>" lines (with
  // optional trailing "+N -N" diff stats) inside an assistant body's
  // .markdown subtree with styled badges. Idempotent — safe to call after
  // every re-render. Operates on text nodes only so existing <code>/<a>
  // children stay intact.
  const FILE_EDIT_RX =
    /\b(Edited|Created) file\s+(\S+?)(?:\s+([+-]\d+)\s+([+-]\d+))?(?=[\s.,;:!?)\]]|$)/g;

  function applyFileEditBadges(rootEl) {
    if (!rootEl) return;
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
    const targets = [];
    let n;
    while ((n = walker.nextNode())) {
      // Skip text already inside a badge (idempotency) or inside <code>/<pre>.
      const p = n.parentNode;
      if (!p) continue;
      if (p.closest && (p.closest(".file-edit-badge") || p.closest("code") || p.closest("pre"))) continue;
      if (FILE_EDIT_RX.test(n.nodeValue)) targets.push(n);
      FILE_EDIT_RX.lastIndex = 0;
    }
    for (const node of targets) {
      const frag = document.createDocumentFragment();
      const text = node.nodeValue;
      let lastIdx = 0;
      let m;
      FILE_EDIT_RX.lastIndex = 0;
      while ((m = FILE_EDIT_RX.exec(text)) !== null) {
        if (m.index > lastIdx) frag.appendChild(document.createTextNode(text.slice(lastIdx, m.index)));
        const badge = document.createElement("span");
        badge.className = "file-edit-badge";
        const verb = document.createElement("span");
        verb.className = "verb";
        verb.textContent = m[1];
        const path = document.createElement("span");
        path.className = "path";
        path.textContent = m[2];
        badge.appendChild(verb);
        badge.appendChild(path);
        // Optional diff stats: m[3] / m[4] arrive as "+32" or "-32".
        if (m[3] && m[4]) {
          const a = document.createElement("span");
          const b = document.createElement("span");
          a.textContent = m[3];
          b.textContent = m[4];
          a.className = m[3].startsWith("+") ? "diff-add" : "diff-del";
          b.className = m[4].startsWith("+") ? "diff-add" : "diff-del";
          badge.appendChild(a);
          badge.appendChild(b);
        }
        frag.appendChild(badge);
        lastIdx = FILE_EDIT_RX.lastIndex;
      }
      if (lastIdx < text.length) frag.appendChild(document.createTextNode(text.slice(lastIdx)));
      node.parentNode.replaceChild(frag, node);
    }
  }

```

**Step 3: Verify**

Run:
```bash
grep -n "function applyFileEditBadges" mcp-servers/tasks/static/preview.html
grep -n "FILE_EDIT_RX" mcp-servers/tasks/static/preview.html
```
Expected: both grep patterns produce 1+ hits, and `applyFileEditBadges` appears on a line before `function renderBubble`.

**Step 4: Smoke-test the regex offline (optional, paste into a browser console on any page)**

```javascript
// Load the helper definition into the console, then:
[..."Edited file index.css +32 -32. Created file src/main.js.".matchAll(FILE_EDIT_RX)].length;
// Expected: 2
```

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): add applyFileEditBadges post-process helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Call `applyFileEditBadges()` from every assistant render path

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — three call-sites

**Step 1: Identify the three sites that write into an assistant `.markdown` subtree**

Run:
```bash
grep -n "\.querySelector(\"\.markdown\").innerHTML" mcp-servers/tasks/static/preview.html
grep -n "contentEl\.innerHTML = renderMarkdown" mcp-servers/tasks/static/preview.html
grep -n "suggBodyEl\.innerHTML = renderMarkdown" mcp-servers/tasks/static/preview.html
```
Expected hits include (line numbers approximate — verify before editing):
- `5572`: `chat-bubble` AI initial render: `el.querySelector(".markdown").innerHTML = renderMarkdown(content);`
- `5649`: chat-mode reply: `aiBubble.querySelector(".markdown").innerHTML = renderMarkdown(replyText);`
- `5433`: build-mode completion: `if (contentEl) contentEl.innerHTML = renderMarkdown(parts.body || "Change applied.");`
- `5435`: build-mode suggestions: `suggBodyEl.innerHTML = renderMarkdown(parts.suggestions);`
- `5445`: build-mode failure: `if (contentEl) contentEl.innerHTML = renderMarkdown(task.result || "Enhancement failed");`

**Step 2: After every `innerHTML = renderMarkdown(...)` write into an AI bubble, call `applyFileEditBadges()` against the same target node**

For each site, append a follow-up call. Examples:

Site 5572 (inside `renderChatBubble`, change the line that already exists):

Old:
```javascript
      if (content) el.querySelector(".markdown").innerHTML = renderMarkdown(content);
```
New:
```javascript
      if (content) {
        const md = el.querySelector(".markdown");
        md.innerHTML = renderMarkdown(content);
        applyFileEditBadges(md);
      }
```

Site 5649 (chat-mode reply):

Old:
```javascript
      aiBubble.querySelector(".markdown").innerHTML = renderMarkdown(replyText);
```
New:
```javascript
      const _md = aiBubble.querySelector(".markdown");
      _md.innerHTML = renderMarkdown(replyText);
      applyFileEditBadges(_md);
```

Site 5433 (build-mode completion):

Old:
```javascript
      if (contentEl) contentEl.innerHTML = renderMarkdown(parts.body || "Change applied.");
```
New:
```javascript
      if (contentEl) {
        contentEl.innerHTML = renderMarkdown(parts.body || "Change applied.");
        applyFileEditBadges(contentEl);
      }
```

Site 5435 (suggestions body):

Old:
```javascript
        suggBodyEl.innerHTML = renderMarkdown(parts.suggestions);
```
New:
```javascript
        suggBodyEl.innerHTML = renderMarkdown(parts.suggestions);
        applyFileEditBadges(suggBodyEl);
```

Site 5445 (build-mode failure):

Old:
```javascript
      if (contentEl) contentEl.innerHTML = renderMarkdown(task.result || "Enhancement failed");
```
New:
```javascript
      if (contentEl) {
        contentEl.innerHTML = renderMarkdown(task.result || "Enhancement failed");
        applyFileEditBadges(contentEl);
      }
```

**Step 3: Verify exactly 5 call-sites exist**

Run:
```bash
grep -c "applyFileEditBadges(" mcp-servers/tasks/static/preview.html
```
Expected: `6` (1 definition + 5 call-sites).

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): wire applyFileEditBadges into all AI render paths

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section 2 — App Builder sidebar icon

### Task 4: Remove the custom "OI" SVG replacement block

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js` — delete the block at lines 1143–1165 (the `cloneIcon.replaceWith(newIcon)` section)

**Step 1: Read current state**

Run:
```bash
sed -n '1142,1167p' mcp-servers/tasks/static/task-panel.js
```
Expected start (verbatim):
```
        entry.setAttribute("title", "App Builder — create and manage AI-built apps");
        // Replace the cloned Workspace SVG with the AIUI "OI" wordmark.
        const cloneIcon = entry.querySelector("svg");
        if (cloneIcon) {
```

**Step 2: Delete lines 1143 through 1165 inclusive (the comment + `const cloneIcon` block, ending with the closing `}` of the `if (cloneIcon)` block)**

After the delete, line 1142 (`entry.setAttribute("title", …)`) must be followed directly by line 1166's content (`// Replace the "Workspace" text label with "Build Website" wherever`).

Use Edit to replace the existing block in one operation. The exact `old_string` to remove is:

```javascript
        entry.setAttribute("title", "App Builder — create and manage AI-built apps");
        // Replace the cloned Workspace SVG with the AIUI "OI" wordmark.
        const cloneIcon = entry.querySelector("svg");
        if (cloneIcon) {
          const ns = "http://www.w3.org/2000/svg";
          const newIcon = document.createElementNS(ns, "svg");
          newIcon.setAttribute("width",  cloneIcon.getAttribute("width")  || "20");
          newIcon.setAttribute("height", cloneIcon.getAttribute("height") || "20");
          newIcon.setAttribute("viewBox", "0 0 32 32");
          if (cloneIcon.getAttribute("class")) newIcon.setAttribute("class", cloneIcon.getAttribute("class"));
          // "OI" wordmark — matches the AIUI brand on the App Builder page.
          const txt = document.createElementNS(ns, "text");
          txt.setAttribute("x", "16");
          txt.setAttribute("y", "22");
          txt.setAttribute("text-anchor", "middle");
          txt.setAttribute("font-family", "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif");
          txt.setAttribute("font-size", "17");
          txt.setAttribute("font-weight", "700");
          txt.setAttribute("fill", "currentColor");
          txt.setAttribute("letter-spacing", "-0.5");
          txt.textContent = "OI";
          newIcon.appendChild(txt);
          cloneIcon.replaceWith(newIcon);
        }
```

The replacement `new_string` keeps the title line:

```javascript
        entry.setAttribute("title", "App Builder — create and manage AI-built apps");
```

**Step 3: Verify the block is gone and label rewrite is intact**

Run:
```bash
grep -c "OI" mcp-servers/tasks/static/task-panel.js
grep -c "cloneIcon" mcp-servers/tasks/static/task-panel.js
grep -c "Workspace.*App Builder" mcp-servers/tasks/static/task-panel.js
```
Expected:
- First two: `0`
- Third: `≥ 1` (the label rewrite at line ~1173 should still be present).

Note: the `App Builder — create and manage AI-built apps` tooltip is still set on the cloned row (see line 1142). That's fine — it's about the row, not an icon.

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "$(cat <<'EOF'
refactor(tasks-panel): keep native Workspace icon in sidebar entry

Drops the custom OI SVG wordmark; cloned row now keeps Open WebUI's
native icon so the App Builder entry visually matches sibling rows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section 3 — Preview viewport toggle

### Task 5: Add `.viewport-toggle` + `.phone-mode` CSS

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — add CSS rules adjacent to the existing `.preview-loading` / `.panel preview-panel` rules. The cleanest spot is right after the `.mode-toggle button.active` rules (around line 1582–1586), since those are the same styling family used here.

**Step 1: Locate insertion point**

Run:
```bash
grep -n "\.mode-toggle button\.active" mcp-servers/tasks/static/preview.html
```
Expected: a hit around line 1582. The closing `}` is around line 1586.

**Step 2: Insert these rules immediately after that closing `}`**

```css
    /* Preview viewport toggle (Desktop / Phone). */
    .viewport-toggle {
      display: inline-flex;
      gap: 0;
      border: 1px solid var(--border);
      border-radius: 999px;
      overflow: hidden;
      margin-right: 6px;
    }
    .viewport-toggle button {
      background: transparent;
      border: 0;
      color: var(--muted);
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      letter-spacing: 0.02em;
    }
    .viewport-toggle button:hover { color: var(--text); }
    .viewport-toggle button.active {
      background: var(--accent-soft);
      color: var(--text);
    }

    /* Phone mode reframes the preview iframe inside #preview-body. */
    #preview-body.phone-mode {
      background: var(--surface);
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 20px 0;
    }
    #preview-body.phone-mode iframe {
      width: 390px;
      max-width: 100%;
      height: 100%;
      max-height: 844px;
      border: 1px solid var(--border);
      border-radius: 12px;
      display: block;
      background: #000;
    }
```

**Step 3: Verify**

Run:
```bash
grep -c "viewport-toggle" mcp-servers/tasks/static/preview.html
grep -c "phone-mode" mcp-servers/tasks/static/preview.html
```
Expected: `≥ 4` and `≥ 2` respectively (CSS rules + soon-to-add JS references).

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
style(preview): add viewport toggle + phone-mode CSS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Add toggle DOM in the preview header

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — insert the toggle inside `<div class="panel-actions">` (line 2117) **before** the existing Refresh button on line 2118

**Step 1: Read current state**

Run:
```bash
sed -n '2117,2122p' mcp-servers/tasks/static/preview.html
```
Expected:
```
          <div class="panel-actions">
            <button class="btn btn-ghost" id="preview-refresh" title="Refresh iframe" disabled>
              <svg width="12" height="12" viewBox="0 0 24 24" ...
              Refresh
            </button>
            <a class="btn btn-ghost" id="preview-open" ...
```

**Step 2: Insert the toggle as the first child of `.panel-actions`**

Use Edit. Old (the line `<div class="panel-actions">` followed by the existing Refresh button start):

```html
          <div class="panel-actions">
            <button class="btn btn-ghost" id="preview-refresh" title="Refresh iframe" disabled>
```

New:

```html
          <div class="panel-actions">
            <div class="viewport-toggle" id="preview-viewport-toggle" role="tablist" aria-label="Preview viewport size">
              <button type="button" data-viewport="desktop" class="active" aria-pressed="true">Desktop</button>
              <button type="button" data-viewport="phone" aria-pressed="false">Phone</button>
            </div>
            <button class="btn btn-ghost" id="preview-refresh" title="Refresh iframe" disabled>
```

**Step 3: Verify the toggle markup landed inside the preview panel head**

Run:
```bash
grep -n "preview-viewport-toggle" mcp-servers/tasks/static/preview.html
```
Expected: 1 hit, line number between 2117 and the Refresh button line.

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): add Desktop/Phone viewport toggle DOM

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Wire the toggle click handler

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — add the wiring in the same area as the existing `$previewRefresh.addEventListener("click", refreshPreviewFrame);` line (around line 3361)

**Step 1: Read current state**

Run:
```bash
sed -n '3360,3363p' mcp-servers/tasks/static/preview.html
```
Expected:
```
  }
  $previewRefresh.addEventListener("click", refreshPreviewFrame);

  // ────────────────────────────────────────────────────────────────────
```

**Step 2: Insert the toggle wiring immediately after the `$previewRefresh.addEventListener` line**

```javascript
  $previewRefresh.addEventListener("click", refreshPreviewFrame);

  // Viewport toggle — flips a phone-mode class on $previewBody. Pure CSS
  // does the rest; no JS resize, no persisted preference (resets on reload).
  const $viewportToggle = document.getElementById("preview-viewport-toggle");
  const $previewBodyEl = document.getElementById("preview-body");
  if ($viewportToggle && $previewBodyEl) {
    $viewportToggle.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-viewport]");
      if (!b) return;
      $viewportToggle.querySelectorAll("button").forEach((x) => {
        const isActive = x === b;
        x.classList.toggle("active", isActive);
        x.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      $previewBodyEl.classList.toggle("phone-mode", b.dataset.viewport === "phone");
    });
  }
```

(Replace the existing single line `$previewRefresh.addEventListener("click", refreshPreviewFrame);` with the block above so the existing line stays at the top of the new block.)

**Step 3: Verify**

Run:
```bash
grep -n "preview-viewport-toggle" mcp-servers/tasks/static/preview.html
grep -n "classList\.toggle(\"phone-mode\"" mcp-servers/tasks/static/preview.html
```
Expected: 2 hits each (DOM + JS reference for the first; CSS rule already exists + JS line for the second).

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): wire viewport toggle to phone-mode class

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Section 4 — Cache-bust and verification

### Task 8: Bump cache-bust query string in `openwebui-overrides/index.html`

**Files:**
- Modify: `openwebui-overrides/index.html:206` — change `?v=20260501-fab` to `?v=20260501-thoughts`

**Step 1: Read current state**

Run:
```bash
sed -n '206p' openwebui-overrides/index.html
```
Expected: `<script src="/tasks/static/task-panel.js?v=20260501-fab"></script>` (or similar — match whatever's currently there).

**Step 2: Replace the version token**

Use Edit. Old:
```html
<script src="/tasks/static/task-panel.js?v=20260501-fab"></script>
```
New:
```html
<script src="/tasks/static/task-panel.js?v=20260501-thoughts"></script>
```

**Step 3: Verify**

Run:
```bash
grep -c "v=20260501-thoughts" openwebui-overrides/index.html
grep -c "v=20260501-fab" openwebui-overrides/index.html
```
Expected: `1` and `0`.

**Step 4: Commit**

```bash
git add openwebui-overrides/index.html
git commit -m "$(cat <<'EOF'
chore(overrides): bump task-panel.js cache-bust for sidebar icon change

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Manual end-to-end verification

**Files:** None modified — this is a verification gate before deploy.

This task is performed by the human user against a running instance (local Caddy stack or production VPS after deploy).

**Step 1: Hard-reload the App Builder page**

Open `https://ai-ui.coolestdomain.win/tasks/app-builder` (or the local equivalent) and hard-reload (`Ctrl+Shift+R`).

**Step 2: Verify the sidebar entry**

In Open WebUI's left sidebar, the entry below "Workspace" should:
- Show Open WebUI's native Workspace icon (briefcase / folder glyph) — **not** the "OI" text
- Read "App Builder"
- Click → navigate to `/tasks/app-builder`

**Step 3: Open a project and trigger a chat reply**

Pick any project, open the preview tab, and type a short question into the ENHANCE chat in **Chat mode** (e.g. "what does this app do?"). When the reply finishes:
- Verify the assistant bubble shows a small uppercase **"Thought"** label at the top of the body
- Verify no `Thought` label appears on the user bubble or while the bubble is in `thinking` state

**Step 4: Trigger a build that edits files**

Switch to **Build mode** and request a small change (e.g. "Change the header color to red"). When the build completes:
- Verify any text like `Edited file index.css +N -N` in the reply body becomes a styled badge: monospace path, green `+N`, red `-N`

**Step 5: Verify the viewport toggle**

Click `Phone` in the preview header. Expected:
- Iframe reframes to a 390 px-wide centered device frame with rounded corners
- Click `Desktop` → returns to full-width iframe
- Click `Refresh` while in Phone mode → iframe reloads, frame stays

**Step 6: Mark complete**

If all six checks pass, mark this task complete. If any fails, file a fix subtask referencing the failing check.

---

## Files touched (summary)

- `mcp-servers/tasks/static/preview.html` — Tasks 1, 2, 3, 5, 6, 7
- `mcp-servers/tasks/static/task-panel.js` — Task 4
- `openwebui-overrides/index.html` — Task 8

No backend, no tests, no new dependencies.

## Out of scope (explicit reminders)

- Persisting viewport choice across reloads
- Tablet / custom viewport sizes
- Milestone / Ideas-to-try-next cards (need backend markers)
- Touching the `+` integrations menu, sidebar Build Website injection logic, or other unrelated panels
- Bumping versions of any other static asset
