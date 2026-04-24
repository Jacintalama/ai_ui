# Preview Page — Enhance Chat Sidebar Design

**Date:** 2026-04-21
**Requested by:** Ralph
**Approved by:** Jacint
**Status:** Design approved, pending implementation

## Summary

Add a **Lovable-style chat sidebar** to the existing preview page (`preview.html`). Admins can type enhancement requests like *"add attendees field to meetings"* and watch the AI modify the running app in real time. Phase labels (`Planning…`, `Building…`, `Verifying…`, `Done`) show what's happening. The iframe auto-refreshes so changes appear immediately.

**Why:** Today, modifying a completed app requires going back to the task panel and creating a new task from scratch. This breaks flow. The chat sidebar lets admins iterate on apps without leaving the preview context — same UX as Lovable and GPT Codex.

## Decisions locked in

| Decision | Choice | Rationale |
|---|---|---|
| Placement | Right sidebar (permanent split) | Matches Lovable. User can see app + chat simultaneously |
| Backend model | New task per enhancement | Clean audit trail. Each enhancement has its own plan/execute/verify |
| Status display | Phase labels (`📋 Planning…` etc.) | What Ralph asked for; matches Lovable/Codex. Not too noisy, not too bare |
| Iframe refresh | Auto on success | No manual click needed |
| Concurrency | One enhancement at a time per app | Prevents git commit collisions |

## Architecture

```
PREVIEW PAGE (preview.html)
┌──────┬──────────────────────────┬─────────────────────────────────┐
│ FILE │  Code / Preview / Tests  │  ✨ ENHANCE CHAT (NEW)          │
│ TREE │  / Logs                  │                                 │
│      │                          │  💬 You: add attendees field    │
│      │  (iframe auto-refreshes  │  🤖 AI: ⚡ Building…            │
│      │   on enhancement done)   │  🤖 AI: ✓ Done (commit abc123)  │
│      │                          │  [Type enhancement...] [Send]   │
└──────┴──────────────────────────┴─────────────────────────────────┘
 220px       flex: 1                     340px
                        │
                        ▼
   NEW: POST /api/tasks/enhance {source_task_id, prompt}
                        │
                        ▼
   Server creates new task.items row (BUILD, max_attempts inherited,
   built_app_slug set, plan_status='approved'), auto-triggers
   _run_execution with ENHANCE_PROMPT_TEMPLATE.
                        │
                        ▼
   Claude CLI runs Red-Green-Refactor on existing apps/<slug>/ files.
   Sidebar polls /tasks/{id} + /executions every 2s to update phase label.
   On COMPLETED, sidebar force-refreshes the preview iframe.
```

## Runtime flow (one enhancement message)

1. User types in sidebar, hits Send
2. Sidebar POSTs `{source_task_id, prompt}` → `/api/tasks/enhance`
3. Server creates new task, starts execution, returns `new_task_id`
4. Sidebar appends user bubble + AI placeholder bubble showing `⏳ Queued`
5. Sidebar polls `/tasks/{new_task_id}` + `/{id}/executions` every 2s
6. Phase label updates: `⚡ Building…` → `✅ Verifying…` → `✓ Done`
7. On completion, sidebar fetches final result + commit, updates bubble, auto-refreshes iframe

## New backend pieces

### `POST /api/tasks/enhance`

```python
# schemas.py
class EnhanceRequest(BaseModel):
    source_task_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)

# routes_tasks.py (or routes_enhance.py)
@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(body: EnhanceRequest, user: AdminUser = Depends(current_admin)):
    # 1. Validate source task is BUILD + has built_app_slug
    # 2. Reject if another enhancement is running for this app (409)
    # 3. Create new task: action_type=BUILD, plan_status='approved',
    #    built_app_slug inherited, description pre-filled with user prompt
    # 4. Build ENHANCE_PROMPT_TEMPLATE, fire _run_execution
    # 5. Return new task
```

### `ENHANCE_PROMPT_TEMPLATE` (new in `claude_executor.py`)

Tells Claude:
- MODIFY existing code in `apps/{slug}/`, don't recreate
- READ existing files first before changing
- Make the SMALLEST change that satisfies the request
- Preserve the existing tech stack (don't switch Python↔Node mid-app)
- Don't delete existing database files; write schema migrations instead
- Keep tests passing; update tests to cover the new behavior (TDD)
- Commit once per enhancement

### `GET /api/tasks?slug=<slug>` extension

Add `slug` filter to existing list endpoint so the sidebar can fetch enhancement history for this app on page load.

## Frontend changes (`preview.html`)

### New sidebar DOM

```html
<aside id="enhance-sidebar" class="sidebar-enhance">
  <header class="enhance-header">
    <span>✨ Enhance</span>
    <button id="enhance-collapse">🗕</button>
  </header>
  <div id="enhance-log" class="enhance-log"></div>
  <div class="enhance-input">
    <textarea id="enhance-prompt" placeholder="Type what to change..."></textarea>
    <button id="enhance-send">Send</button>
  </div>
</aside>
```

### Layout adjustment

Current layout is 2 columns (tree + tabbed content). Becomes 3 columns:
- `220px file tree` | `flex: 1 tabbed content` | `340px enhance sidebar`
- Uses CSS grid or flex with explicit widths
- Sidebar collapses via `display:none` + a toggle on the preview header

### Phase derivation logic

```javascript
function derivePhaseLabel(task, latestExec) {
  const log = (latestExec && latestExec.log) || "";
  const attempt = task.attempt_count;
  const max = task.max_attempts;
  if (task.status === "completed") return { label: "✓ Done", commit: extractCommit(task.result) };
  if (task.status === "failed")    return { label: "✗ Failed", detail: task.result };
  if (task.status === "awaiting_input") return { label: "❓ Needs input", detail: task.result, needsReply: true };
  if (task.status === "running") {
    if (attempt > 0) return { label: `🔄 Retrying (${attempt}/${max})…` };
    if (log.includes("--- VERIFY STEP ---")) return { label: "✅ Verifying…" };
    return { label: "⚡ Building…" };
  }
  return { label: "⏳ Queued" };
}
```

### Polling

- 2-second interval while a bubble is in-progress
- Stop on terminal status
- On `completed`, force-refresh the iframe by rewriting its `src` with a new cache-buster timestamp

### Input behavior

- Enter submits, Shift+Enter newline
- Send button disabled while any enhancement is in flight
- Character counter (warn at 1500, max 2000)
- Optimistic UI: user bubble appears instantly; AI placeholder shows `⏳ Queued` until first poll returns real status

### History on page load

On page load (after file tree fetch), sidebar calls `GET /api/tasks?status=done&slug=<slug>&limit=20` and renders prior enhancements as collapsed bubbles (oldest first). User can scroll up to see full history.

## Error handling

| Case | Behavior |
|---|---|
| Source task has no `built_app_slug` | Sidebar disabled with "This task has nothing to enhance" |
| Empty input | Client-side, don't POST |
| 409 concurrent | Inline warning "Wait for current enhancement to finish" |
| 500 server error | Red bubble with error, re-enable Send, no auto-retry |
| 401 (token expired) | Stop polling, show "Session expired — refresh page" |
| Claude NEEDS_INPUT | Bubble shows question + inline reply textarea, posts to existing `/answer` endpoint |
| 3 retries failed | Red bubble, link to "View full log" opens existing log modal |
| Browser closed mid-enhancement | Task keeps running server-side; on next load, history fetch shows in-flight state, polling resumes |

## One-at-a-time concurrency

Backend rejects with 409 if another enhancement for the same `built_app_slug` is in `running`, `planning`, or `awaiting_input`. This prevents:
- Two enhancements making conflicting git commits
- Two Claude subprocesses editing the same files
- Confusing half-merged state

Sidebar enforces the same on the UI side for immediate feedback (Send disabled while any bubble is still in progress).

## Why skip CLARIFY and PLAN for enhancements

Enhancement prompts are short, targeted. The user already wrote the exact change. Plan review would kill the fast-iteration flow Ralph is asking for. So:
- `plan_status='approved'` set at creation — skips the plan-review gate
- Task goes directly to TDD EXECUTE
- VERIFY still runs (that's the safety net)
- Loop retry still fires on failure (3 attempts)

The full CLARIFY → PLAN → EXECUTE → VERIFY pipeline is preserved for brand-new loop-mode BUILD tasks. Enhancements just take a shortcut.

## Files touched

| File | Change |
|---|---|
| `mcp-servers/tasks/claude_executor.py` | Add `ENHANCE_PROMPT_TEMPLATE` + `build_enhance_prompt()` |
| `mcp-servers/tasks/schemas.py` | Add `EnhanceRequest` |
| `mcp-servers/tasks/routes_tasks.py` | Add `slug` filter to list_tasks; add `/enhance` endpoint |
| `mcp-servers/tasks/static/preview.html` | Add chat sidebar DOM, CSS, polling, phase derivation, iframe auto-refresh |
| `docs/plans/2026-04-21-preview-enhance-chat-plan.md` | Implementation plan (next step) |

No database migration needed. No new columns.

## What's NOT in scope (YAGNI)

- Threading enhancements with `parent_task_id` — the `built_app_slug` filter already groups them. Revisit if history UI gets crowded.
- Undo/revert button — use git to revert a bad enhancement manually for now.
- Streaming live Claude output in the sidebar — Section 2 noted this as "Option 3"; can add a "Show details" expand later if users ask.
- Multi-user collaboration (typing indicators, presence) — overkill for a small team tool.
- Suggested-prompts / autocomplete — maybe later.

## Success criteria

1. Ralph opens preview page for meeting-notes → sees chat sidebar on the right
2. Types *"add attendees field"* → sees his bubble immediately + AI bubble with `⏳ Queued`
3. Within 30 seconds, bubble transitions through `⚡ Building…` → `✅ Verifying…` → `✓ Done (commit sha)`
4. Iframe auto-refreshes, new attendees field visible in the running app
5. Types a 2nd enhancement → works the same way
6. Refreshes the page → sees both enhancements in history, collapsed at top

## References

- Previous work: `docs/plans/2026-04-16-decision-engine-loop-preview-design.md`
- Prior harder-build test: `docs/plans/2026-04-17-harder-build-test-result.md`
- Lovable.dev — inspiration for sidebar UX
- GPT Codex (ChatGPT) — inspiration for phase labels
