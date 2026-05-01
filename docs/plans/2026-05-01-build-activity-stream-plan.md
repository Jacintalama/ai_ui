# Live Build Activity Stream Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render a live activity stream of the agent's tool calls (Edit, Read, Bash, Grep, Glob, Web) inside the build bubble while a task is running, replacing the static "Building…" indicator with progress feedback.

**Architecture:** Pure client-side. Add a `.build-activity` container to the assistant-bubble template, plus two helpers: `parseToolCallsFromLog(logText)` walks the executor's stream-json output and yields tool-call events; `renderBuildActivity(containerEl, events)` writes them into the container. `updateAiBubble` calls them on every 2-second poll while task status is `running`. On terminal status, the container is hidden and the existing THOUGHT-card body takes over unchanged.

**Tech Stack:** Vanilla JS + CSS in `mcp-servers/tasks/static/preview.html`. No backend changes, no new dependencies.

**Reference design:** `docs/plans/2026-05-01-build-activity-stream-design.md`

---

## Task 1: Add `.build-activity` CSS

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — insert after the existing `.enhance-bubble.ai.done .cancel-action, .enhance-bubble.ai.failed .cancel-action { display: none; }` rule (currently around line 1534).

**Step 1: Read current state**

Run:
```bash
sed -n '1532,1538p' mcp-servers/tasks/static/preview.html
```

Expected:
```
    .enhance-bubble.ai.done .cancel-action,
    .enhance-bubble.ai.failed .cancel-action { display: none; }

    .enhance-empty {
```

(Line numbers may shift slightly if other commits land first; the unique anchor is the `.done .cancel-action, .failed .cancel-action` rule.)

**Step 2: Insert this CSS block immediately after the closing `}` of `.failed .cancel-action`**

```css
    /* Live build activity stream — shown only while a build task is running.
       Renders a scrollable list of the agent's tool calls (Edit/Read/Bash/…)
       parsed from the executor's stream-json log. Hidden when the bubble
       reaches a terminal status. */
    .enhance-bubble.ai .build-activity {
      max-height: 240px;
      overflow-y: auto;
      margin: 8px 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .enhance-bubble.ai .build-activity:empty { display: none; }
    .enhance-bubble.ai .build-activity .activity-line {
      font-family: var(--font-mono);
      font-size: 11.5px;
      line-height: 1.5;
    }
    .enhance-bubble.ai .build-activity .activity-line .verb {
      font-weight: 600;
      margin-right: 6px;
    }
    .enhance-bubble.ai .build-activity .activity-read   { color: var(--text-2); }
    .enhance-bubble.ai .build-activity .activity-bash   { color: #c084fc; }
    .enhance-bubble.ai .build-activity .activity-grep,
    .enhance-bubble.ai .build-activity .activity-glob   { color: #86efac; }
    .enhance-bubble.ai .build-activity .activity-web    { color: #60a5fa; }
    .enhance-bubble.ai .build-activity .activity-other  { color: var(--muted); }
    /* Edit/Write events reuse the existing .file-edit-badge styling from
       the THOUGHT-card feature (see line ~1487 onward). No new rule needed. */
```

**Step 3: Verify**

```bash
grep -c "Live build activity stream" mcp-servers/tasks/static/preview.html  # expect 1
grep -c "\.build-activity" mcp-servers/tasks/static/preview.html             # expect ≥ 8
grep -c "\.activity-line" mcp-servers/tasks/static/preview.html              # expect ≥ 2
```

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
style(preview): add build-activity stream CSS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `parseToolCallsFromLog` + `renderBuildActivity` helpers

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — insert immediately AFTER `function applyFileEditBadges` (currently ends around line 5540) and BEFORE `function renderBubble` (currently line 5542).

**Step 1: Locate insertion point**

```bash
grep -n "^  function applyFileEditBadges\|^  function renderBubble" mcp-servers/tasks/static/preview.html
```

Expected (line numbers approximate):
```
5492:  function applyFileEditBadges(rootEl) {
5542:  function renderBubble(kind, content, opts) {
```

The end of `applyFileEditBadges` is the line `}` immediately before the blank line that precedes `function renderBubble`. Confirm with:
```bash
sed -n '5538,5544p' mcp-servers/tasks/static/preview.html
```

Expected (whitespace-sensitive):
```
      node.parentNode.replaceChild(frag, node);
    }
  }

  function renderBubble(kind, content, opts) {
```

**Step 2: Insert the two helpers between `}` (end of `applyFileEditBadges`) and the blank line before `function renderBubble`**

Insert this block:

```javascript
  // Walk the executor's stream-json log (one JSON object per line) and yield
  // one event per assistant tool_use. Drops tool_result, prose, system, and
  // session-result lines. Used by renderBuildActivity below to render the
  // live activity stream while a build task is running.
  function parseToolCallsFromLog(logText) {
    const events = [];
    if (!logText) return events;
    const lines = String(logText).split("\n");
    for (const raw of lines) {
      const line = raw.trim();
      if (!line || line[0] !== "{") continue;
      let obj;
      try { obj = JSON.parse(line); } catch (_) { continue; }
      if (obj.type !== "assistant" || !obj.message || !Array.isArray(obj.message.content)) continue;
      for (const c of obj.message.content) {
        if (c.type !== "tool_use") continue;
        const name = c.name || "tool";
        const inp = c.input || {};
        if (name === "Edit" || name === "Write") {
          if (inp.file_path) events.push({ kind: "edit", verb: "Editing", path: String(inp.file_path) });
        } else if (name === "Read") {
          if (inp.file_path) events.push({ kind: "read", verb: "Reading", target: String(inp.file_path) });
        } else if (name === "Bash") {
          if (inp.command) events.push({ kind: "bash", verb: "Run", target: String(inp.command).slice(0, 90) });
        } else if (name === "Grep") {
          if (inp.pattern) events.push({ kind: "grep", verb: "Grep", target: String(inp.pattern).slice(0, 60) });
        } else if (name === "Glob") {
          if (inp.pattern) events.push({ kind: "glob", verb: "Glob", target: String(inp.pattern).slice(0, 60) });
        } else if (name === "WebSearch" || name === "WebFetch") {
          events.push({ kind: "web", verb: "Web", target: String(inp.url || inp.query || "").slice(0, 90) });
        } else {
          events.push({ kind: "other", verb: name, target: "" });
        }
      }
    }
    return events;
  }

  // Render a list of tool-call events into a container. Idempotent — safe to
  // call on every poll. Edit/Write events use the existing file-edit-badge
  // styling (matches the THOUGHT-card visual); everything else uses a plain
  // .activity-line with a kind-tinted color. Auto-scrolls to the bottom.
  function renderBuildActivity(containerEl, events) {
    if (!containerEl) return;
    if (!events || events.length === 0) {
      containerEl.innerHTML = "";
      containerEl.hidden = true;
      return;
    }
    const out = [];
    for (const e of events) {
      if (e.kind === "edit") {
        out.push(
          '<span class="file-edit-badge">' +
            '<span class="fe-verb">' + escapeHtml(e.verb) + '</span>' +
            '<span class="fe-path">' + escapeHtml(e.path) + '</span>' +
          '</span>'
        );
      } else {
        out.push(
          '<div class="activity-line activity-' + escapeHtml(e.kind) + '">' +
            '<span class="verb">' + escapeHtml(e.verb) + '</span>' +
            '<span class="target">' + escapeHtml(e.target || "") + '</span>' +
          '</div>'
        );
      }
    }
    containerEl.innerHTML = out.join("");
    containerEl.hidden = false;
    containerEl.scrollTop = containerEl.scrollHeight;
  }

```

**Step 3: Verify**

```bash
grep -n "function parseToolCallsFromLog\|function renderBuildActivity" mcp-servers/tasks/static/preview.html
# Expect 2 hits, both before "function renderBubble"
awk '/function parseToolCallsFromLog/{a=NR} /function renderBuildActivity/{b=NR} /function renderBubble\(kind, content, opts\)/{c=NR} END{print a, b, c, (a<b && b<c ? "OK" : "WRONG ORDER")}' mcp-servers/tasks/static/preview.html
```

**Step 4: Smoke-test the parser offline**

Run with node:
```bash
node -e "
const SAMPLE = [
  '{\"type\":\"system\",\"subtype\":\"init\"}',
  '{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Read\",\"input\":{\"file_path\":\"src/main.css\"}}]}}',
  '{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Edit\",\"input\":{\"file_path\":\"src/index.html\"}}]}}',
  '{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Bash\",\"input\":{\"command\":\"npm install --silent\"}}]}}',
  '{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\",\"tool_use_id\":\"abc\",\"content\":\"ok\"}]}}',
  'plain text line',
  '',
].join('\n');
function parseToolCallsFromLog(logText) {
  const events = [];
  if (!logText) return events;
  const lines = String(logText).split('\n');
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line[0] !== '{') continue;
    let obj; try { obj = JSON.parse(line); } catch (_) { continue; }
    if (obj.type !== 'assistant' || !obj.message || !Array.isArray(obj.message.content)) continue;
    for (const c of obj.message.content) {
      if (c.type !== 'tool_use') continue;
      const name = c.name || 'tool';
      const inp = c.input || {};
      if (name === 'Edit' || name === 'Write') events.push({kind:'edit',verb:'Editing',path:inp.file_path});
      else if (name === 'Read') events.push({kind:'read',verb:'Reading',target:inp.file_path});
      else if (name === 'Bash') events.push({kind:'bash',verb:'Run',target:String(inp.command).slice(0,90)});
      else events.push({kind:'other',verb:name,target:''});
    }
  }
  return events;
}
console.log(JSON.stringify(parseToolCallsFromLog(SAMPLE), null, 2));
"
```

Expected output: array of 3 events — Read, Edit, Run — ignoring the system / tool_result / plain-text / empty lines.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): add stream-json parser + activity renderer helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `.build-activity` container to the bubble template

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — inside `renderBubble` (currently line 5542), modify the assistant branch's `innerHTML` template.

**Step 1: Read current state**

```bash
sed -n '5550,5570p' mcp-servers/tasks/static/preview.html
```

Expected:
```javascript
    if (kind === "user") {
      el.innerHTML = '<div class="body"></div>';
      el.querySelector(".body").textContent = content || "";
    } else {
      el.innerHTML =
        '<div class="body">' +
          '<span class="phase-inline"><span class="phase-icon">⏳</span><span class="phase-text">Queued</span></span>' +
          '<div class="markdown content"></div>' +
          '<div class="suggestions" style="display:none;">' +
            '<div class="suggestions-label">💡 Ideas to try next</div>' +
            '<div class="markdown suggestions-body"></div>' +
          '</div>' +
          '<button class="cancel-action" type="button" style="display:none;" title="Cancel this enhancement">✕ Cancel</button>' +
          '<div class="commit-footer" style="display:none;"></div>' +
        '</div>';
    }
```

**Step 2: Insert the activity container between `phase-inline` and `markdown content`**

Use Edit. Old:
```javascript
      el.innerHTML =
        '<div class="body">' +
          '<span class="phase-inline"><span class="phase-icon">⏳</span><span class="phase-text">Queued</span></span>' +
          '<div class="markdown content"></div>' +
```

New:
```javascript
      el.innerHTML =
        '<div class="body">' +
          '<span class="phase-inline"><span class="phase-icon">⏳</span><span class="phase-text">Queued</span></span>' +
          '<div class="build-activity" hidden></div>' +
          '<div class="markdown content"></div>' +
```

**Step 3: Verify**

```bash
grep -c '<div class="build-activity"' mcp-servers/tasks/static/preview.html  # expect 1
grep -n 'build-activity' mcp-servers/tasks/static/preview.html | head -10
```

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): add build-activity container to bubble template

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire activity render into `updateAiBubble`

**Files:**
- Modify: `mcp-servers/tasks/static/preview.html` — inside `updateAiBubble` (currently line 5588), add activity-render logic.

**Step 1: Read current state**

```bash
sed -n '5588,5610p' mcp-servers/tasks/static/preview.html
```

Expected start:
```javascript
  function updateAiBubble(bubbleEl, task, latestExec) {
    const phase = derivePhase(task, latestExec);
    // If the task we were replying to has moved past awaiting_input (user
    // answered, task is now running/completed/failed), drop reply mode.
    if (awaitingReplyTo === task.id && task.status !== "awaiting_input") {
      setReplyMode(null);
    }
    const iconEl = bubbleEl.querySelector(".phase-icon");
    const textEl = bubbleEl.querySelector(".phase-text");
    const contentEl = bubbleEl.querySelector(".content");
    const suggEl = bubbleEl.querySelector(".suggestions");
    const suggBodyEl = bubbleEl.querySelector(".suggestions-body");
    const commitEl = bubbleEl.querySelector(".commit-footer");
    const cancelBtn = bubbleEl.querySelector(".cancel-action");
    if (iconEl) iconEl.textContent = phase.icon;
    if (textEl) textEl.textContent = phase.text;
```

**Step 2: Add activity wiring immediately after the `if (textEl) textEl.textContent = phase.text;` line and before the `if (task.status === "completed")` block**

Use Edit. Old:
```javascript
    if (iconEl) iconEl.textContent = phase.icon;
    if (textEl) textEl.textContent = phase.text;

    if (task.status === "completed") {
```

New:
```javascript
    if (iconEl) iconEl.textContent = phase.icon;
    if (textEl) textEl.textContent = phase.text;

    // Live build activity — shown only while running. Cleared on terminal.
    const activityEl = bubbleEl.querySelector(".build-activity");
    if (activityEl) {
      if (task.status === "running") {
        const events = parseToolCallsFromLog((latestExec && latestExec.log) || "");
        renderBuildActivity(activityEl, events);
      } else {
        activityEl.innerHTML = "";
        activityEl.hidden = true;
      }
    }

    if (task.status === "completed") {
```

**Step 3: Verify**

```bash
grep -c "parseToolCallsFromLog(" mcp-servers/tasks/static/preview.html  # expect 2 (1 def + 1 call)
grep -c "renderBuildActivity(" mcp-servers/tasks/static/preview.html    # expect 2 (1 def + 1 call)
grep -n "Live build activity — shown only while running" mcp-servers/tasks/static/preview.html  # expect 1 hit
```

**Step 4: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "$(cat <<'EOF'
feat(preview): wire build activity stream into updateAiBubble

While task.status === "running", parse the executor's stream-json log
and render tool-call events into the .build-activity container.
On terminal status, clear and hide the container so the THOUGHT body
takes over unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Bump cache-bust query string

**Files:**
- Modify: `openwebui-overrides/index.html:206`

**Step 1: Read current state**

```bash
sed -n '206p' openwebui-overrides/index.html
```

Expected current value: `?v=20260501-thoughts` (from the previous feature deploy).

**Step 2: Replace token**

Use Edit. Old:
```html
<script src="/tasks/static/task-panel.js?v=20260501-thoughts"></script>
```

New:
```html
<script src="/tasks/static/task-panel.js?v=20260501-activity"></script>
```

**Step 3: Verify**

```bash
grep -c "v=20260501-activity" openwebui-overrides/index.html   # expect 1
grep -c "v=20260501-thoughts" openwebui-overrides/index.html   # expect 0
```

**Step 4: Commit**

```bash
git add openwebui-overrides/index.html
git commit -m "$(cat <<'EOF'
chore(overrides): bump cache-bust for build activity stream

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Manual end-to-end verification

**Files:** None modified — verification gate before declaring done.

**Step 1: Hard-reload the App Builder page**

`https://ai-ui.coolestdomain.win/tasks/app-builder/?t=tasks-tracker` (or another running project), `Ctrl+Shift+R`.

**Step 2: Trigger a Build-mode prompt**

Switch the ENHANCE chat to **Build** mode and send a small request (e.g. "tweak the header padding to 16 px").

**Step 3: Verify activity stream during run**

While the task is running, the bubble should show:
- The "Building…" phase indicator at the top
- BELOW it, a scrolling list that grows over the next 10–60 seconds with lines like:
  - `Reading src/index.html`
  - `Editing src/index.html` (boxed badge style, monospace)
  - `Run npm install` (purple monospace)
- No emoji anywhere in the activity stream
- No `tool_result`/`✓` lines, no assistant prose chunks

**Step 4: Verify completion transition**

When the build finishes:
- Activity list disappears
- THOUGHT card body fills in with the agent's summary (image #11 layout)
- "IDEAS TO TRY NEXT" suggestions show if present
- `commit <sha>` footer shows

**Step 5: Verify failure transition (optional — only if you have a way to force a failure)**

Send a deliberately broken request. On failure:
- Activity stream disappears
- Bubble flips to red `.failed` state with the error message
- No leftover activity lines

**Step 6: Mark complete**

If all steps pass, mark this task complete. If any fails, file a fix subtask referencing the failing step.

---

## Files touched (summary)

- `mcp-servers/tasks/static/preview.html` — Tasks 1, 2, 3, 4
- `openwebui-overrides/index.html` — Task 5

No backend, no tests, no new dependencies. Total estimated line delta: +24 CSS, +56 JS helpers, +1 DOM line, +9 wire-up = ~90 net lines added.

## Out of scope (reminders)

- Tool-result `✓`/`✗` lines (Q2=A)
- Assistant prose chunks in the stream (Q2=A)
- Persisting the activity log after completion (Q1=A)
- Animating line-by-line arrival
- Cross-bubble activity history
