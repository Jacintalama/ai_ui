# Friendly Date/Time Picker for Schedules — Design Spec

**Date:** 2026-06-09
**Status:** Approved (high-level), pending spec review
**Author:** brainstormed with Jacint

## 1. Problem & Goal

Today, setting a schedule means typing a free-text *"How often?"* phrase (e.g. *"every Monday 9am"*) that `schedule_parse.parse_when` turns into a cron expression. Non-technical users find free text intimidating and easy to get wrong. Goal: a **click-driven date/time picker** so a user can set up a schedule **without typing time phrases** — and, as a new capability, schedule a **one-time** run (not just repeating).

Locked decisions (from brainstorming):

| Decision | Choice |
|---|---|
| Schedule kinds | **Both** repeating AND one-time, from the same picker |
| Discord one-time date | **Quick-pick buttons** ([Today][Tomorrow][Next Monday]) **+ a "next 14 days" dropdown** (Discord has no native calendar) |
| Discord time | **Hourly dropdown** (00:00–23:00, Manila) for v1; exact minutes via the text fallback |
| Slack | **Native Block Kit `datepicker` + `timepicker`** (and a Repeat dropdown) |
| Monthly repeating | **Deferred to phase 2** |
| Free-text "when" | **Kept** as a power-user fallback (nothing existing breaks) |

Non-goals (v1): monthly/yearly recurrence presets; per-minute granularity in the Discord dropdown; timezones other than Manila (the platform is single-tz today); editing the *timing* of an existing schedule via the picker (edit still uses the text modal in v1).

## 2. User-facing flow

The picker is the new front of the **➕ New schedule** path (in the user's private thread on Discord / the schedule modal on Slack). It replaces the *"How often?"* text field; the *"What should it do?"* task field stays.

### Discord (buttons + dropdowns — no native calendar)

Step A — kind:
```
⏰ When should this run?
   [ 🔁 Repeating ]     [ 1️⃣ Just once ]
```

Step B(repeating):
```
How often?  [ Every day ▾ ]   (Every day · Weekdays · Every week · Every hour · Every 30 min)
What time?  [ 9:00 AM ▾ ]     (hourly, Manila GMT+8 — hidden for "Every hour/30 min")
Which day?  [ Monday ▾ ]      (only for "Every week")
            [ ✅ Set the task ]
```

Step B(just once):
```
Which day?  [ Today ] [ Tomorrow ] [ Next Monday ]   or  [ Pick a date ▾ ]  (next 14 days)
What time?  [ 9:00 AM ▾ ]
            [ ✅ Set the task ]
```

Step C — **✅ Set the task** opens a modal with one field, *"What should it do?"* (paragraph). On submit, the schedule is created and confirmed in the thread (reusing the existing confirm card).

### Slack (native pickers)

The schedule modal gains:
- a **Repeat** static-select (One time · Every day · Weekdays · Every week · Every hour · Every 30 min),
- a native **`timepicker`**,
- a **weekday** static-select (shown for weekly),
- a native **`datepicker`** (used only when Repeat = "One time"),
- plus the existing *"What should it do?"* input.

Slack collects everything in one modal submit (no multi-step needed).

## 3. Architecture & data flow

The picker's only job is to produce **(cron_expr, run_once, human_label)** — exactly what the schedule create path already consumes (plus the new `run_once`). All downstream scheduling is unchanged.

```
User clicks picks (Discord dropdowns / Slack pickers)
        │
        ▼
picks → schedule_picker.picks_to_cron(kind, freq, time, day|date)  [PURE, unit-tested]
        │     repeating → cron like "0 9 * * 1"  (reuses parse_when's cron grammar)
        │     one-time  → cron "MIN HR DAY MON *" + run_once=True; reject if the
        │                 resolved Manila datetime is in the past
        ▼
create_schedule(..., cron_expr, run_once, prompt)  ──HTTP──▶ tasks: POST /schedules
        │                                                      INSERT schedules(..., run_once)
        ▼
scheduler._tick_once (unchanged matching) fires when cron matches the minute
        │   on fire: mark last_run_at=now; **if run_once → also set enabled=false**
        ▼
agent runs → result delivered to the thread/DM (existing path)
```

**Why a cron + `run_once` flag (not a separate one-time table):** the scheduler's `cron_matches_now` already fires `"30 9 15 6 *"` at exactly June 15 09:30 Manila. The only thing that would make it repeat is the yearly match — so flipping `enabled=false` the moment it fires makes it truly one-time, with **one tiny scheduler change** and zero new matching logic.

### The Discord multi-step state problem (and the solution)

Discord modals hold only text inputs, and each dropdown emits its own interaction — so the picks must accumulate across interactions. Solution: **carry the running selection forward in the next components' `custom_id`s** (stateless), and have the final **✅ Set the task** button open a modal whose `custom_id` encodes the fully-resolved `cron_expr` + `run_once`. The modal submit reads the task text + decodes the timing → creates the schedule. No server-side pending state needed (custom_ids easily fit `"30 9 15 6 *|once"`). If a future pattern overflows the 100-char custom_id limit, fall back to the existing **token → pending-schedule map** pattern already used by the connector gate (`_pending_schedules`).

## 4. Components to build

### 4.1 `webhook-handler/handlers/schedule_picker.py` (NEW — pure)
- Constants for the new `custom_id` namespace (e.g. `aiuisched:pick:*`) and the option lists (frequencies, hourly times, weekdays, quick-pick dates, 14-day dropdown).
- `picks_to_cron(kind, freq=None, hhmm=None, weekday=None, date_iso=None, *, now) -> (cron_expr, run_once, human_label)` — the pure converter. Reuses `parse_when`'s cron grammar/validation; reuses `_fmt_time`/`_DAY_NAME` for labels. Raises/returns an error sentinel for a past one-time datetime.
- Discord card builders: the kind card, the repeating-picks card, the one-time-picks card, and the "Set the task" modal (one paragraph field whose custom_id carries the resolved timing).
- Unit-tested in `tests/test_schedule_picker.py`.

### 4.2 Discord routing — `discord_commands.py`
Route the new `aiuisched:pick:*` buttons/selects: render the next step (carrying state in custom_ids), and on the "Set the task" modal submit, decode the timing + read the task → call the existing schedule-create router method with `cron_expr` + `run_once`.

### 4.3 Slack — `slack_schedule_panel.py` + `slack_interactions.py`
Add the Repeat static-select, native `timepicker`, weekday select, and native `datepicker` to the schedule modal; in `view_submission`, read those Block Kit values → `picks_to_cron` → create. (Slack `datepicker` returns `YYYY-MM-DD`, `timepicker` returns `HH:MM` — feed straight into the converter.) These pickers **replace** the free-text *"How often?"* input in the Slack create modal (no redundant text "when" field — Slack goes picker-only). The text fallback in 4.5 refers to **Discord's** existing text-modal path, which stays available.

### 4.4 Backend — run-once support (`mcp-servers/tasks`)
- **Migration** `0NN_schedule_run_once.sql`: `ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS run_once BOOLEAN NOT NULL DEFAULT FALSE;` (idempotent; migrations run every boot).
- **Model**: add `run_once` to the `Schedule` SQLAlchemy model.
- **`scheduler._tick_once`**: in the pre-dispatch update for a firing row, if `sched.run_once` is True, also set `enabled=False` (fires exactly once, then off). No change to `should_fire`/`cron_matches_now`.
- **Create route + client**: `CreateScheduleIn` gains `run_once: bool = False`; the route passes it into `s.add(Schedule(..., run_once=body.run_once))`; `TasksClient.create_schedule` sends it (default False — fully backward-compatible). v1 does **not** need `run_once` in `_serialize`/read-back — the schedule card already shows the date/time via `cron_to_human`; a distinct "one-time" badge is phase 2.

### 4.5 Keep the text fallback
The existing free-text *"How often?"* modal path on **Discord** (`SCHED_MODAL_ID`) stays wired and unchanged, so power users (and the picker's "exact minute" gap) are covered. (Slack's create modal becomes picker-only per 4.3.)

## 5. Error handling
- **Past one-time datetime**: `picks_to_cron` rejects it; the bot replies "That time is already past — pick a future time." No schedule is created.
- **Incomplete picks** (e.g. weekly with no weekday, or "Set the task" before a time is chosen): the "Set the task" button is only offered once the required picks are present; defensively, the converter validates and the bot asks for the missing piece.
- **Invalid/garbled custom_id state**: treated as a no-op with a friendly "Let's start over" prompt (mirrors the existing malformed-custom_id handling).
- **Backward compatibility**: existing schedules have `run_once=false` (column default) → behave exactly as today.

## 6. Testing strategy
Pure/unit where possible; **no production DB** (the tasks `conftest` `db_session` TRUNCATEs — only run targeted pure test files locally via the webhook-handler venv, per the outreach feature's setup).
- `schedule_picker.picks_to_cron`: repeating presets → correct cron (daily/weekdays/weekly+day/hourly/every-30); one-time date+time → `"MIN HR DAY MON *"` + run_once=True; past datetime → rejected; labels correct. Table-driven.
- Discord picker builders: card/option shapes, custom_id round-trip (encode timing → decode in modal submit).
- Discord routing: kind button → repeating/one-time card; "Set the task" modal submit → create called with the right cron + run_once (mirror `test_schedules_ux_interactions.py`).
- Slack: modal value extraction → `picks_to_cron`; datepicker/timepicker formats.
- **Scheduler run-once** (pure, no DB): a focused test that a `run_once` row, when fired in `_tick_once`, is updated to `enabled=False` (assert the update path) — and that `run_once=False` rows are untouched. Reuse the existing scheduler test conventions.
- `create_schedule` client: `run_once` sent in the payload.

## 7. Scope & phasing
- **v1 (this spec):** the picker (Discord dropdowns/quick-picks + Slack native pickers) for repeating presets (Daily/Weekdays/Weekly/Hourly/Every-30) and one-time runs; the `run_once` backend; text fallback retained.
- **Phase 2 (later):** Monthly/custom recurrence; :30 / finer times in the Discord dropdown (2-step hour→minute); editing an existing schedule's timing via the picker; one-time "natural date" parsing in the text fallback.

## 8. Files touched (summary)
- NEW `webhook-handler/handlers/schedule_picker.py` (+ test)
- `webhook-handler/handlers/discord_commands.py` (routing)
- `webhook-handler/handlers/slack_schedule_panel.py` + `slack_interactions.py` (native pickers)
- `webhook-handler/clients/tasks.py` (`create_schedule` gains `run_once`)
- `mcp-servers/tasks/migrations/0NN_schedule_run_once.sql` (new column)
- `mcp-servers/tasks/models.py` (`Schedule.run_once`)
- `mcp-servers/tasks/scheduler.py` (`_tick_once`: disable run_once after fire)
- the tasks schedule-create route (persist `run_once`)
