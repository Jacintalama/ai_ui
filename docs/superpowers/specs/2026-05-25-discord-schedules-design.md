# Discord Schedules — Design Spec

**Date:** 2026-05-25
**Status:** Approved (brainstorm) → implementing

## Goal

Let **non-technical** Discord users create and manage recurring AI tasks ("cron jobs") **without slash commands and without cron syntax**, and **see the results in their private thread**. Both *personal* tasks ("summarize my unread emails every morning") and *app-tied* tasks ("email me my coffee-shop app's orders weekly") are supported — app-tying is implicit via the prompt text (the agent runs in the user's workspace), so no extra UI is needed for it in v1.

## Why this matters

The tasks-service scheduler already runs a Claude agent on a cron (`mcp-servers/tasks/scheduler.py`), but the result lands only in the DB (`last_run_status`, the task log) — **nothing reaches the user**. So scheduled work is currently invisible/useless. The two halves of this feature are: (1) a friendly Discord creation/management UX, and (2) **result delivery** back to the user's Discord thread.

## Non-goals (v1)

- Per-app "⏰ Schedule" button inside the app menu (phase 2 — deep-links into the same create flow with the prompt pre-seeded).
- Timezone picker (default `Asia/Manila`).
- Editing an existing schedule's time/prompt (v1 = create + delete + pause/run-now).

## Architecture

Two services, one new cross-service callback.

```
Discord user
   │  (buttons + modal, no slash command)
   ▼
webhook-handler  ──create_schedule(..., delivery_channel_id)──▶  tasks service  (stores Schedule row)
   ▲                                                                   │  cron fires, agent runs
   │  POST /internal/schedule-result  ◀──────────────────────────────┘  _finalize_run posts result
   ▼
Discord private thread (result shown to user)
```

### Component A — webhook-handler (Discord side, fully TDD'd)

**`handlers/schedule_parse.py`** (new, pure): `parse_when(text) -> (cron_expr, human_readable) | None`. Ports `parse_schedule` from `mcp-servers/scheduler/main.py`. Handles "every morning"→`0 8 * * *`, "every day at 8pm", "every monday at 9am", "every 30 minutes", "hourly"/"daily"/"weekly", and 5-field cron passthrough. Returns `None` if unparseable. Unit-tested with many phrases.

**`handlers/app_builder_panel.py`** (extend, pure builders + custom_id scheme). New prefix family `aiuisched:`:
- `aiuisched:new` — "⏰ New schedule" button (opens modal)
- `aiuisched:modal` — create modal (2 text inputs: `what` = paragraph, `when` = short)
- `aiuisched:confirm:<token>` / `aiuisched:cancel:<token>` — confirmation card buttons
- `aiuisched:list` — "📋 My schedules" button
- `aiuisched:run:<id>` / `aiuisched:pause:<id>` / `aiuisched:del:<id>` — per-row actions

New builders: `build_schedules_panel()`, `build_schedule_modal()`, `build_confirm_components(token)`, `build_schedule_list_components(schedules)`; predicates/extractors mirroring the existing `is_*`/`*_from_*` style. Confirmation card carries a short `token` (uuid4 hex) in the custom_id; the parsed schedule data lives in an in-memory pending store (TTL ~10 min) keyed by that token — same pattern as the build-watcher tasks.

**`handlers/discord_commands.py`** (extend interaction routing): new branches for the buttons/modal above. Flow:
1. `aiuisched:new` button → respond with MODAL (`build_schedule_modal()`).
2. `aiuisched:modal` submit → `parse_when(when)`; if `None`, respond ephemerally asking to rephrase; else stash `{user_email, name, cron, prompt, tz}` under a token and respond with an **ephemeral confirmation card** (parsed summary + Confirm/Cancel).
3. `aiuisched:confirm:<token>` → ensure a private thread for the user (reuse current thread if the interaction is already in one, else `create_private_thread` + `add_thread_member`); call `TasksClient.create_schedule(..., delivery_channel_id=<thread id>)`; edit the ephemeral to "✅ Scheduled".
4. `aiuisched:list` → `TasksClient.list_schedules`; render ephemeral list with per-row Run/Pause/Delete.
5. `aiuisched:run|pause|del:<id>` → call the matching TasksClient method; update the ephemeral.

**`clients/tasks.py`** (extend): add `delivery_channel_id` param to `create_schedule`; add `pause_schedule`, `run_schedule_now` (POST `/schedules/{id}/disable` and `/run-now`). Still sends **only `X-User-Email`** (unchanged security invariant).

**`main.py`** (extend): new endpoint `POST /internal/schedule-result`, body `{channel_id, schedule_name, status, result}`, auth via `X-Internal-Secret == INTERNAL_CALLBACK_SECRET` env (shared with tasks). Posts a formatted message to `channel_id` via `DiscordClient.post_channel_message` (already exists). Returns 403 on bad/missing secret.

### Component B — tasks service (written + compile-checked; not locally test-run)

**`models.py`**: add `delivery_channel_id = Column(Text, nullable=True)` to `Schedule`.

**`migrations/0XX_schedule_delivery_channel.sql`**: `ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS delivery_channel_id text;` (idempotent — matches the existing migration style).

**`routes_schedules.py`**: add `delivery_channel_id: str | None = None` to `CreateScheduleIn`, persist it, include in `_serialize`.

**`scheduler.py`** `_finalize_run`: after the run completes, if `sched.delivery_channel_id` is set, read the task's `result` and `POST {WEBHOOK_HANDLER_URL}/internal/schedule-result` with the `X-Internal-Secret` header. Best-effort: failures are logged, never crash the tick. Result is `scrub()`'d before sending.

**`docker-compose.unified.yml`**: add `WEBHOOK_HANDLER_URL=http://webhook-handler:8086` and `INTERNAL_CALLBACK_SECRET=${INTERNAL_CALLBACK_SECRET:-}` to the `tasks` service env; add the same secret to `webhook-handler`. (`.env.example` documents it.)

## Data flow (create → fire → deliver)

1. User clicks **⏰ New schedule** → modal → types *what* + *when*.
2. webhook-handler parses *when*→cron, shows ephemeral confirm card.
3. Confirm → ensure private thread → `create_schedule(delivery_channel_id=thread)`.
4. Cron matches (tasks ticker) → agent runs → `_finalize_run` → `POST /internal/schedule-result`.
5. webhook-handler posts the result into the user's private thread.

## Error handling

- Unparseable *when* → ephemeral "I couldn't read that time — try 'every morning' or 'every Monday 9am'."
- `TasksAPIError` (status 0 / 4xx) → mapped to friendly ephemeral text (reuse `_format_status_error` pattern).
- Delivery callback failures → logged in tasks, never break the tick; the run still records `last_run_status`.
- `/internal/schedule-result` without the shared secret → 403.

## Security

- `/internal/schedule-result` requires `X-Internal-Secret`; only the tasks container has it. Results go only to private threads.
- `TasksClient` continues to send **only** `X-User-Email` (never the cron secret) — ownership enforced server-side.
- Bot token stays solely in webhook-handler (tasks never gets it).

## Testing

- `schedule_parse`: pure unit tests (phrase table + cron passthrough + failure cases).
- panel builders: pure-function shape tests (mirror `test_app_builder_panel.py`).
- interaction routing: button→modal, modal→confirm (parsed + unparseable), confirm→`create_schedule` called with `delivery_channel_id`, list render, run/pause/del dispatch.
- `/internal/schedule-result`: posts to Discord on good secret; 403 on bad.
- `TasksClient` new/changed methods: respx tests, assert only `X-User-Email` sent.
- All run in `webhook-handler/.venv` (currently 140 green).

## Honest scope

- Component A: full TDD, all green locally.
- Component B: written + `compileall`-checked; the tasks suite needs deps I can't install here, and live Discord/VPS smoke needs a deploy. Those are the only unverified-here steps and will be called out at handoff.
