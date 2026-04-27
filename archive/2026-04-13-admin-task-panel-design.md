# Admin Task Approval Panel — Design

**Date:** 2026-04-13
**Status:** Draft (pending review)
**Author:** Brainstorming session with Ralph

## Problem

Meeting transcripts are processed by the existing `meetings` service, which runs an AI summarizer and a decision engine. The decision engine extracts action items and currently posts BUILD / INTEGRATE / ASK_USER items to Discord, where they are easy to miss. There is no record of which items were acted on, no per-admin filtering, no execution mechanism beyond manual work, and no audit trail.

The 4 admins (Ralph, Clarenz, Lukas, Jacint) need a single surface inside the AIUI website (Open WebUI) that shows them the action items assigned to them, lets them choose to do the work themselves or have the AI do it autonomously on the server, and tracks history of what has been done. Future work will extend this to non-admin users — the data model must not be admin-specific.

## Goals

- Each admin sees only the action items assigned to them, sourced from the latest meeting transcripts in `meetings.records`.
- An admin can approve a task to be executed by AI (Claude Code remote on the server) or claim it for manual handling.
- AI execution streams progress to the admin in real time and gracefully falls back to asking the admin for input or producing manual steps when it cannot proceed autonomously.
- The system records all completed tasks (with mode, timestamp, result) so admins can review their history.
- The UI lives inside Open WebUI as a floating panel, auto-pops on login when there are pending tasks, can be minimized or closed, and can be reopened from the Integrations menu.

## Non-goals

- Replacing Discord notifications entirely. Discord can continue to receive a copy if desired; the panel is the source of truth.
- Building a generic task tracker. This is purpose-built for meeting action items.
- Self-serve user onboarding. The 4 admins are seeded via a config map; full user expansion is future work.
- AI execution for arbitrary commands. AI execution is scoped to BUILD and INTEGRATE action items via the existing `mcp-auth` Claude Code remote channel.
- Re-running RESEARCH tasks. RESEARCH items are already auto-executed by the meetings service (`execute_research` in `decision_engine.py`); they appear in the Done tab as historical records only, with no `⚡ AI` / `✋ Manual` buttons on the card.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Open WebUI page (browser)                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Task Panel (injected JS overlay, ~520px wide, top-right)  │  │
│  │  - Pending / In Progress / Done tabs                      │  │
│  │  - Auto-pops on login if pending tasks exist              │  │
│  │  - Minimize collapses to badge; close hides until reopen  │  │
│  │  - Reopen from Integrations menu                          │  │
│  │  - SSE stream during AI execution                         │  │
│  │  - "See full history →" link to /tasks/history page       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────────────────┘
                      │ HTTPS (Open WebUI JWT)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ NEW: tasks service (FastAPI) — port 8210                        │
│  - GET  /api/tasks?status=pending           list for current    │
│         &assignee_user_id=<self>            user                │
│  - GET  /api/tasks/history                  paginated archive   │
│  - POST /api/tasks/{id}/execute             start AI run (SSE)  │
│  - POST /api/tasks/{id}/manual              claim for manual    │
│  - POST /api/tasks/{id}/answer              answer ASK_USER     │
│  - POST /api/tasks/{id}/complete            mark manual done    │
│  - POST /webhooks/meeting-action-items      ingest from         │
│                                             meetings service    │
│  - GET  /api/tasks/{id}/stream              SSE for live status │
└──────┬───────────────────────────┬──────────────────────────────┘
       │                           │
       ▼                           ▼
┌─────────────────┐        ┌─────────────────────────────────────┐
│ PostgreSQL      │        │ mcp-auth → Claude Code remote       │
│ tasks schema    │        │ (executes BUILD/INTEGRATE on server)│
└─────────────────┘        └─────────────────────────────────────┘
       ▲
       │ webhook (POST on each new meeting)
┌─────────────────────────────────────────────────────────────────┐
│ existing meetings service                                       │
│ Decision engine in meetings/decision_engine.py is modified to   │
│ call the tasks service webhook in addition to (or instead of)   │
│ posting to Discord.                                             │
└─────────────────────────────────────────────────────────────────┘
```

Boundaries:
- **meetings service** keeps its current responsibility: store transcripts, summarize, classify action items.
- **tasks service** owns approval, execution, and history.
- **Task panel JS** is delivered through Open WebUI's "Custom JS" admin setting, following the existing `mcp-servers/gdrive/integrations-ui.js` pattern.

## Data Model

New `tasks` schema in the existing PostgreSQL instance (the same DB used by `meetings`).

### `tasks.items`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `gen_random_uuid()` |
| `meeting_id` | UUID | FK → `meetings.records.id` |
| `action_type` | text | `RESEARCH` / `BUILD` / `INTEGRATE` / `ASK_USER` |
| `assignee_name` | text | Raw from decision engine ("Ralph Benitez") |
| `assignee_user_id` | UUID | Open WebUI user id (resolved via assignee map) |
| `description` | text | What needs to be done |
| `query` | text | Short query string from decision engine |
| `priority` | text | `CRITICAL` / `IMPORTANT` / `NICE_TO_HAVE` |
| `status` | text | `pending` → `claimed_manual` / `running` / `awaiting_input` / `completed` / `failed` |
| `mode` | text \| null | `ai` or `manual` once admin chooses |
| `result` | text \| null | Final output, manual steps, or admin's answer |
| `created_at` | timestamptz | `default now()` |
| `updated_at` | timestamptz | trigger-updated on row update |
| `completed_at` | timestamptz \| null | set when status reaches `completed` or `failed` |

Indexes:
- `(assignee_user_id, status)` for the panel's main query.
- `(assignee_user_id, completed_at desc)` for history tab pagination.
- `(meeting_id)` for joins back to source meeting.

### `tasks.executions`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `task_id` | UUID | FK → `tasks.items.id` |
| `started_at` | timestamptz | |
| `finished_at` | timestamptz \| null | |
| `status` | text | `running` / `succeeded` / `failed` / `needs_input` |
| `log` | text | Streamed Claude Code output (so we can replay to a reconnecting SSE client) |
| `error` | text \| null | Failure reason if `status = failed` |

A separate executions table allows multiple AI attempts per task (failure → admin replies → AI retries) without losing prior context.

### Assignee → User mapping

For 4 admins, a config-map approach is sufficient. Add to `.env.example`:
```
TASKS_ASSIGNEE_MAP=ralph:<openwebui-user-uuid>,clarenz:<uuid>,lukas:<uuid>,jacint:<uuid>
```

The tasks service ingests an action item with `assignee_name` like "Ralph Benitez" and matches it against the map: each map key (e.g., `ralph`) is treated as a case-insensitive prefix of the incoming `assignee_name`. First match wins. If no key matches, `assignee_user_id` is set to a sentinel "team" id and the item shows up for all 4 admins.

## API Surface

All endpoints require an Open WebUI JWT (validated via the existing API gateway). The current admin's user id is taken from the JWT — clients cannot list other users' tasks.

| Method | Path | Body / Query | Behavior |
|--------|------|--------------|----------|
| `GET` | `/api/tasks` | `?status=pending\|progress\|done&limit=50` | Returns tasks for the current admin in the requested status. |
| `GET` | `/api/tasks/history` | `?limit=50&offset=0&from=<date>&type=<type>` | Paginated archive, current admin only. |
| `POST` | `/api/tasks/{id}/execute` | (empty) | Starts AI execution. Returns immediately with `execution_id`. Client opens SSE stream. |
| `GET` | `/api/tasks/{id}/stream` | `?from=<line_offset>` (SSE) | Streams `data: {line_no, log_chunk, status}` events. On reconnect, client passes the last `line_no` it saw via `from=` and the server replays from that offset before resuming live. Closes when execution finishes. |
| `POST` | `/api/tasks/{id}/manual` | (empty) | Sets `status=claimed_manual`, `mode=manual`. |
| `POST` | `/api/tasks/{id}/complete` | `{result: string}` | Marks a manual task done, fills `result` and `completed_at`. |
| `POST` | `/api/tasks/{id}/answer` | `{answer: string}` | Submits ASK_USER reply or feeds back into a stalled AI run. |
| `POST` | `/api/tasks/{id}/cancel` | (empty) | Cancels an in-flight AI execution (kills the Claude Code process, sets `status=failed` with cancellation reason). |
| `POST` | `/webhooks/meeting-action-items` | `{meeting_id, items: [...]}` | Internal webhook from the meetings service. Idempotent on `(meeting_id, description)`. |

Status transitions:
- `pending` → `running` (execute) → `completed` / `failed` / `awaiting_input`
- `pending` → `claimed_manual` (manual) → `completed` (complete)
- `awaiting_input` → `running` (answer) → ...

## AI Execution Flow

When the admin clicks **⚡ AI** on a BUILD or INTEGRATE task:

1. Panel calls `POST /api/tasks/{id}/execute`.
2. Tasks service updates `status=running`, inserts a row in `tasks.executions`, builds the prompt below, and posts to `mcp-auth` to launch a Claude Code remote run.
3. Claude Code reads the repository, makes changes, runs commands. It streams stdout back to the tasks service over the mcp-auth channel.
4. The tasks service buffers each chunk into `executions.log` and broadcasts it as an SSE event to any open `/api/tasks/{id}/stream` clients.
5. Claude Code ends its response with one of the following sentinels:
   - `COMPLETED: <summary>` → `status=completed`, `result=summary`, `completed_at=now()`
   - `NEEDS_INPUT: <question>` → `status=awaiting_input`, `result=question`. Panel switches to ASK_USER UI for that task.
   - `NEEDS_STEPS: <markdown>` → `status=claimed_manual`, `mode=manual`, `result=markdown`. Panel renders the steps inline.
6. The SSE stream closes when execution finishes for any reason.

Prompt template:
```
You are executing a task from the AIUI meeting decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}
SOURCE: {meeting_title} on {meeting_date}

Repository: /workspace/ai_ui (you have full access via mcp-auth)

Complete the task autonomously. If you cannot proceed because of:
  - Missing credentials → respond ending with: NEEDS_INPUT: <what you need>
  - Unclear requirement → respond ending with: NEEDS_INPUT: <clarifying question>
  - Hard blocker → respond ending with: NEEDS_STEPS: <numbered manual steps>

When done successfully, respond ending with: COMPLETED: <summary of what you did>
```

Safety:
- 5-minute default timeout per execution. Admin sees a "Stop" button that POSTs to `/api/tasks/{id}/cancel`.
- Commits made by AI use the assignee's git identity, not Claude's, so the audit trail is on the human who approved.
- AI execution runs entirely server-side; the admin's machine is never involved.

## UI Behavior

Floating panel injected into Open WebUI via custom JS, following the pattern in `mcp-servers/gdrive/integrations-ui.js`:

- **Width:** 520px. **Position:** fixed, 24px from top and right edges.
- **Auto-popup:** On Open WebUI page load, fetch pending tasks. Open the panel if there are any AND the admin hasn't dismissed it in the last 4 hours (tracked in localStorage).
- **Tabs:** `Pending | In Progress | Done`, each with a count pill. Switching tabs lazy-loads if the data is stale.
- **Refresh:** Manual ⟳ button in the header re-fetches the current tab.
- **Minimize:** ─ collapses to a small badge in the corner showing the pending count. Click to expand.
- **Close:** ✕ hides the panel until reopen via the Integrations menu or until next login.
- **Footer:** "See full history →" link opens a separate `/tasks/history` page (paginated full archive).
- **No background polling.** Refresh is on-demand. The only live channel is the SSE stream during an active AI execution.

Per-task cards:
- Pending: type badge, priority badge, description, assignee, source meeting, action buttons (`⚡ AI` + `✋ Manual`, or `💬 Answer` for ASK_USER).
- In Progress: same plus a live status line showing the current step from the SSE stream and a `⏹ Stop` button.
- Done: ✓ done indicator, mode used (`⚡ AI` or `✋ Manual`), completed timestamp, expandable to show the saved `result`.

## Failure Modes

| Failure | Detection | Behavior |
|---------|-----------|----------|
| Meetings webhook arrives with malformed items | Pydantic validation | 400 to caller, log error. No partial inserts. |
| Decision engine emits item with no recognizable assignee | Map lookup miss | Item assigned to "team" sentinel; visible to all 4 admins. |
| AI execution hangs past timeout | 5-min deadline | Process killed, `status=failed`, error message in execution row. |
| AI execution produces no sentinel | End of stream without `COMPLETED`/`NEEDS_*` | Treat as `failed`, panel shows "AI did not return a result — try Manual". |
| SSE client disconnects mid-stream | Connection drop | Server keeps writing to `executions.log`. On reconnect, replay log then continue streaming. |
| User clicks "AI" twice on same task | Partial unique index: `CREATE UNIQUE INDEX ON tasks.executions (task_id) WHERE status = 'running'` | Second request returns existing `execution_id`. |
| Same action item ingested twice (re-process meeting) | Webhook idempotency on `(meeting_id, description)` | Existing task is updated, not duplicated. |

## Testing Strategy

- **Unit:** Pydantic schemas, status transitions, sentinel parsing, assignee map resolution.
- **Integration (real Postgres, real meetings DB):** Webhook ingestion → query for assignee → mark complete. No mocked DB.
- **AI execution path:** Mock the mcp-auth call but use real prompt construction; assert correct status transitions on each sentinel.
- **SSE:** Test that disconnect-and-reconnect replays the log, then continues live.
- **Manual end-to-end:** Trigger a real meeting in the DB, verify items appear in panel for the right admin, click AI, verify Claude Code remote execution proceeds.

## Open Questions

- Should completed tasks ever be deleted (retention policy), or kept indefinitely? Default to indefinite for now.
- Do we need a notification mechanism (badge in OpenWebUI nav, email, push) for new tasks arriving while the admin is offline? Not in v1; the auto-popup on next login is enough.
- Should `ASK_USER` answers be posted back into the source meeting record (`meetings.records.summary` or a new `answers` field)? Recommended yes — it closes the loop. Treat as a follow-up after v1 ships.

## Future Work

- Extend to non-admin users: the data model already supports it; only the assignee map and Open WebUI permissions need to change.
- Optional Discord mirror: post a single "task created" message with a link to the panel, in addition to (or instead of) the current per-item posts.
- Slack integration as an alternative notification channel.
- Bulk operations on the history page (re-run failed tasks, export to CSV).
