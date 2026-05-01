# Live Build Activity Stream — Design

**Date:** 2026-05-01
**Branch:** `feat/gdrive-gmail-connectors`
**File primarily affected:** `mcp-servers/tasks/static/preview.html`

## Problem

When a user submits a Build-mode prompt, the chat bubble shows only a static "Building…" line with a Cancel button until the build completes. There is no visible feedback about what the agent is actually doing — reading files, editing files, running commands. For a 30–60 second build the user stares at a frozen "Building…" indicator and can't tell whether anything is happening.

The agent already produces rich structured output (the executor uses Claude CLI with `--output-format stream-json`, so each tool call lands as its own JSON line in the execution log). The floating Open WebUI task panel even has a parser for these lines (`task-panel.js:543`, `prettifyStreamLine`) — but the build-mode bubble in `preview.html` does not use it. So the data is there; the UI just hasn't been wired up.

## Goal

While a Build task is running, render a live activity stream of the agent's tool calls (Edit, Read, Bash, Grep, Glob, WebSearch) inside the same bubble. On task completion, hide the activity stream so the existing THOUGHT card body takes over unchanged.

## Non-goals

- No backend or SSE schema changes. The executor already emits stream-json; the polling client already fetches the full log every 2 s.
- No tool-result `✓` / `✗` indicators (out of scope per Q2=A).
- No assistant prose chunks in the activity stream (out of scope per Q2=A).
- No persistence of activity after completion (Q1=A — collapses into the THOUGHT card).
- No animation or staggered line-arrival effects.
- No cross-bubble or cross-task activity log.

## Approach

Pure client-side feature. Three pieces:

1. **Template change** — `renderBubble` adds a new `.build-activity` container between the `.phase-inline` indicator and the `.markdown.content` body. Initially hidden.
2. **Parser** — `parseToolCallsFromLog(logText)` walks the executor log line-by-line, JSON-parses lines that look like stream-json, and yields one event per `tool_use` content block. Tool results, prose chunks, and session markers are dropped.
3. **Renderer** — `renderBuildActivity(containerEl, events)` writes the events into the container. `Edit` / `Write` events render as `file-edit-badge` spans (matching the existing THOUGHT-card badges from the previous feature). Everything else renders as a plain `activity-line` with monospace font and subtle color tint per tool kind.

The renderer is idempotent: every poll re-parses the full log and replaces `containerEl.innerHTML`. Safe because the log is small (KB range) and polls are throttled to 2 s.

`updateAiBubble` is the wire-up point. While `task.status === "running"`, it calls the renderer and shows the container. On `completed` / `failed`, it hides the container; the existing `splitCompletion` flow then renders the THOUGHT body in `.markdown.content` as today.

## Components

### 1. DOM template addition

Inside the assistant branch of `renderBubble` (currently lines ~5554–5566 of `preview.html`), insert:

```html
<div class="build-activity" data-role="activity" hidden></div>
```

between the existing `<span class="phase-inline">…</span>` and `<div class="markdown content"></div>`.

### 2. Parser — `parseToolCallsFromLog(logText)`

Walks `logText.split("\n")`. For each line:
- Trim. If it does not start with `{`, skip.
- `JSON.parse(line)`; if it throws, skip.
- If `obj.type === "assistant"` and `obj.message.content` is an array, walk each `c`:
  - If `c.type === "tool_use"`, classify by `c.name` and produce an event:

| `name`                  | event                                                              |
|-------------------------|--------------------------------------------------------------------|
| `Edit`, `Write`         | `{kind: "edit",  verb: "Editing",  path:   input.file_path}`       |
| `Read`                  | `{kind: "read",  verb: "Reading",  target: input.file_path}`       |
| `Bash`                  | `{kind: "bash",  verb: "Run",      target: input.command.slice(0, 90)}` |
| `Grep`                  | `{kind: "grep",  verb: "Grep",     target: input.pattern.slice(0, 60)}` |
| `Glob`                  | `{kind: "glob",  verb: "Glob",     target: input.pattern.slice(0, 60)}` |
| `WebSearch`, `WebFetch` | `{kind: "web",   verb: "Web",      target: input.url || input.query}`   |
| anything else           | `{kind: "other", verb: c.name,     target: ""}`                    |

- All other line types (`tool_result`, `text`, `system`, `result`) are dropped.

Returns an ordered array of event objects.

### 3. Renderer — `renderBuildActivity(containerEl, events)`

- If `events` is empty: hide the container, return.
- Otherwise unhide and rebuild `containerEl.innerHTML` from a string-built fragment.
- For `kind === "edit"`: render as
  ```html
  <span class="file-edit-badge"><span class="fe-verb">Editing</span><span class="fe-path">{escapeHtml(path)}</span></span>
  ```
  (uses the existing CSS from the THOUGHT-card feature.)
- For everything else: render as
  ```html
  <div class="activity-line activity-{kind}"><span class="verb">{verb}</span><span class="target">{escapeHtml(target)}</span></div>
  ```
- After write: `containerEl.scrollTop = containerEl.scrollHeight` so the latest event is in view.

### 4. Wire-up in `updateAiBubble`

After the existing phase / icon / text writes, add:

```js
const activityEl = bubbleEl.querySelector(".build-activity");
if (activityEl) {
  if (task.status === "running") {
    const events = parseToolCallsFromLog((latestExec && latestExec.log) || "");
    renderBuildActivity(activityEl, events);
  } else {
    activityEl.hidden = true;
    activityEl.innerHTML = "";
  }
}
```

The clear-on-terminal also frees memory and ensures the THOUGHT body has a clean visual region.

### 5. Styling

```css
.build-activity {
  max-height: 240px;
  overflow-y: auto;
  margin: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.build-activity .activity-line {
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.5;
}
.build-activity .activity-line .verb {
  font-weight: 600;
  margin-right: 6px;
}
.build-activity .activity-read   { color: var(--text-2); }
.build-activity .activity-bash   { color: #c084fc; }
.build-activity .activity-grep,
.build-activity .activity-glob   { color: #86efac; }
.build-activity .activity-web    { color: #60a5fa; }
.build-activity .activity-other  { color: var(--muted); }
```

The two hardcoded hex colors (`#c084fc`, `#86efac`, `#60a5fa`) are already used by `prettifyStreamLine` in `task-panel.js` for the same tool kinds; copying the palette keeps the two surfaces visually consistent.

## Data flow

```
poll every 2s ─► /executions ─► latestExec.log (full text)
                                     │
                                     ▼
                       parseToolCallsFromLog
                                     │
                                     ▼
                            events: [{kind, verb, ...}, ...]
                                     │
                                     ▼
                       renderBuildActivity (idempotent)
                                     │
                                     ▼
                       .build-activity container DOM
```

When `task.status` flips to `completed`, the wire-up clears `.build-activity` and the existing `parts.body / parts.suggestions / parts.sha` flow paints the THOUGHT card body in `.markdown.content` as today.

## Error handling

- Malformed JSON lines are silently skipped.
- Missing `input.file_path` / `input.command` / `input.pattern` falls through to the `other` kind label.
- Empty `latestExec` or empty `latestExec.log` produces an empty events array, which hides the container.
- The two new helpers are pure (no side effects, no DOM access except `renderBuildActivity` writing to its argument). No new global state.

## Files touched

- `mcp-servers/tasks/static/preview.html` — CSS rules (~24 lines) + DOM template line + 2 helpers (~50 lines) + wire-up (~10 lines)

No other files affected. The cache-bust query string in `openwebui-overrides/index.html` will be bumped as the final implementation step before deploy, same pattern as the previous feature.
