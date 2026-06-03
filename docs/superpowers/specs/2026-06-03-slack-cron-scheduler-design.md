# Slack Cron Scheduler — Design

**Date:** 2026-06-03
**Status:** Design — approved in brainstorming, pending spec review

## Problem

The cron/scheduler feature (schedule a recurring task in plain English; results delivered to a
private space) exists only on Discord. The scheduler **backend** (the `tasks.schedules` table, the
CRUD routes, the cron tick loop, plain-English parsing) is largely platform-agnostic, BUT the
**delivery** path is hardcoded to Discord: `scheduler.py::_deliver_to_discord` POSTs to a
Discord-only `/internal/schedule-result` endpoint that formats Discord markdown and posts via the
Discord client into a per-user Discord thread. Slack has no scheduler UX at all.

## Goal

Bring the cron scheduler to Slack: a `#cron-job` panel, a plain-English create form, a per-user
schedule dashboard, and per-schedule actions — with each run's **result delivered to the user's
Slack DM**. Reuse the shared backend; add a platform-aware delivery seam.

## Approved decisions (brainstorm)
- **Delivery target:** the user's private **DM** (consistent with App Builder builds; Slack has no per-user threads).
- **Create form:** mirror Discord — plain-English "what" + "when", parsed by the existing `parse_when`.
- **Connector gating:** **skip for v1** (no Gmail/Drive pre-check).

## Architecture

One platform-aware delivery seam + a new Slack UX layer. The schedule CRUD, the cron tick, and
task execution are unchanged.

### Backend (tasks service) — additive
- `migrations/018_schedule_delivery_platform.sql`: `ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS delivery_platform text DEFAULT 'discord'` (existing rows → `discord`, preserving current behavior).
- `models.py` `Schedule`: add `delivery_platform = Column(Text, ...)`.
- `routes_schedules.py`: `CreateScheduleIn` accepts optional `delivery_platform` (default `discord`); persist it on create.
- `scheduler.py`: generalize `_deliver_to_discord` → `_deliver_result(channel_id, platform, name, status, result, schedule_id)`; `_finalize_run` reads `sched.delivery_platform` and passes it through. The POST to the webhook-handler now includes `platform`.

### webhook-handler
- `main.py` `/internal/schedule-result`: accept a `platform` field. `platform == "slack"` → format the run result as Slack mrkdwn and `slack_client.post_message(channel_id, …)` (channel_id = the user's DM channel), with a Retry button on a failed run. Otherwise the existing Discord path (unchanged).
- `clients/tasks.py`: `create_schedule(..., delivery_platform="slack")` parameter (passed in the POST body).
- **New** `handlers/slack_schedule_panel.py` — Block Kit builders mirroring the Discord ones:
  `build_schedules_panel` (pinned `#cron-job` entry: "⏰ Open my schedules"), `build_schedules_dashboard` (New + list), `build_schedule_card` (one schedule + Run/Pause/Resume/Edit/Delete), `build_schedule_modal` / `build_schedule_edit_modal` (what + when). Reuse the `aiuisched:*` id strings (action_ids).
- `slack_interactions.py`: route `aiuisched:*` block_actions (open → open DM + post dashboard; new → open modal; run/pause/resume/del/edit → call the tasks-client method + re-render; select → show card) and `view_submission` for the create + edit modals.
- A setup step to post + pin the scheduler panel in the existing `#cron-job` channel (`C0B8TK8MYHW`).

### Reuse (unchanged)
`schedule_parse.parse_when`; all `clients/tasks.py` schedule methods (`list_schedules`, `create_schedule`, `delete_schedule`, `pause_schedule`, `resume_schedule`, `run_schedule_now`, `update_schedule`); the cron tick + execution; the `aiuisched:*` id strings.

## Data flow

```
#cron-job: [ ⏰ Open my schedules ]
  → resolve email (_bail_if_not_linked); open the user's DM; post the dashboard (New + existing list)
[ ➕ New schedule ] → modal (what + when)
  → submit → parse_when(when) → create_schedule(email, name, cron, prompt,
        delivery_channel_id=<user DM channel>, delivery_platform="slack")
  → "✅ Scheduled: <name> — runs <when>" in the DM
Cron tick matches → _finalize_run → _deliver_result(dm_channel, "slack", …)
  → webhook-handler /internal/schedule-result (platform=slack)
  → slack_client.post_message(dm_channel, formatted result [+ Retry on failure])
Per-schedule actions (Run/Pause/Resume/Edit/Delete) → existing tasks-client methods → re-render dashboard
```

## Error handling
- **Not linked → no email** (schedules are keyed by `user_email`): resolve via `_bail_if_not_linked`; unlinked → "link your account first" (it DMs the prompt and stops). This is account-linking, not connector gating.
- **DM can't be opened** (`im:write` missing): fall back to an ephemeral message in `#cron-job` (existing pattern).
- **`parse_when` can't parse the "when"**: friendly "couldn't understand that schedule time — try e.g. 'every morning at 8am'."
- **Delete**: direct action (mirrors Discord; schedules are cheap to recreate — no confirm step).
- **Delivery is best-effort** in the tick loop (never raises into the scheduler), same as today.

## Testing (TDD)
- **Backend:** migration idempotent; `create_schedule` persists `delivery_platform`; `_finalize_run` passes the schedule's platform to `_deliver_result`.
- **webhook endpoint:** `platform="slack"` → `slack_client.post_message(channel_id, …)` (mocked); Discord path unchanged for `platform="discord"`/absent.
- **Slack builders:** panel has the Open-my-schedules button; dashboard has New + a list; create modal has what + when inputs; card has Run/Pause/Resume/Edit/Delete.
- **Slack handlers:** open → opens DM + posts dashboard; new → opens modal; modal submit → `parse_when` + `create_schedule(delivery_platform="slack", delivery_channel_id=<dm>)`; actions → correct tasks-client calls; edit modal → `update_schedule`.

## Scope guard (YAGNI)
- No change to the cron tick, schedule execution, or the Discord flow (only generalize delivery).
- Plain-text create form (no Slack rich pickers).
- No connector gating in v1.
- Schedule delete is direct (no confirm).

## Out of scope
- Connector (Gmail/Drive) gating on Slack.
- Changing schedule semantics, cron parsing, or execution.
- Migrating existing Discord schedules.
