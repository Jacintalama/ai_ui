# Schedules UX Redesign — Design Spec

**Date:** 2026-05-25
**Status:** Approved (brainstorm) → implementing
**Builds on:** `feat/discord-quick-wins`

## Problem (from user feedback + screenshots)
The current Schedules UX is messy and lives in the shared #app-builder channel:
- Raw cron shown (`-/5 * * *`), confusing `last run: running`, ugly auto-names
  (`discord-aiui.teams-/5 * * *`), and bare "Deleted."/"Paused." replies pile up.
- All management happens via stacked button-rows in the shared channel.
- Users want a **private per-user space**, a **dropdown** to pick a schedule,
  and **clean, human-readable** text.

## Design (approved)

### Flow
1. **#app-builder** pinned panel → just **⏰ Open my schedules** + **🔗 Link my account**.
2. **Open my schedules** → ensure/reuse the user's **private thread** `schedules-<user>`
   (only they + the bot) → post the **dashboard** there → edit the ephemeral ACK to
   point at the thread (`→ <#thread>`).
3. **Dashboard** (in thread): **➕ New schedule** button + a **▼ Pick a schedule**
   dropdown (one option per schedule, human-readable label + status).
4. **Select** a schedule → post a clean **card** for it with **▶ Run now / ⏸ Pause
   (or ▶ Resume) / ✏️ Edit / 🗑 Delete**.
5. **Card actions update the card in place** (no new pile-up messages): pause flips
   the button to Resume and the status to ⏸; delete blanks the card to "🗑 Deleted".
6. **New / Edit** → modal → on success, confirmation in the thread.
7. **Run results** continue to land in the same thread.

### Clean messages
- New `cron_to_human(cron)` formatter: `*/5 * * * *`→"every 5 minutes",
  `0 8 * * *`→"every day at 8:00 AM", `0 9 * * 1`→"every Monday at 9:00 AM",
  `0 * * * *`→"every hour". Exotic crons fall back to the raw expression.
- New `schedule_status_label(schedule)`: 🟢 active / ⏸ paused / ⏳ running now /
  ✅ active · last run ok / ⚠️ active · last run failed.
- Dropdown option: label = `<cron_to_human> — <prompt first line>`, description = status.
- Card: `📅 <prompt>` / `🕒 <cron_to_human>` / `<status label>`.

## Components

### webhook-handler (TDD, all green)
`handlers/schedule_format.py` (new, pure): `cron_to_human`, `schedule_status_label`,
`schedule_label(schedule)` (dropdown label).

`handlers/app_builder_panel.py` (extend):
- `SCHED_OPEN_ID = "aiuisched:open"`, `SCHED_SELECT_ID = "aiuisched:select"`.
- `build_schedules_panel()` → **changed** to [⏰ Open my schedules] + [🔗 Link].
- `build_schedules_dashboard(schedules)` → {content, components}: New button + (dropdown if any).
- `build_schedule_select(schedules)` → string-select (value=id, label/desc from formatter; ≤25).
- `build_schedule_card(schedule)` → {content, components}: clean text + state-aware action row.
- `build_deleted_card()` → "🗑 Deleted." with no components.
- Remove `build_schedule_list` (replaced); keep run/pause/resume/del/edit prefixes.

`handlers/commands.py` (router):
- `run_schedules_dashboard(ctx)` → resolve email, list, `ctx.respond_components(dashboard)`.
- `run_schedule_card(ctx, schedule_id)` → fetch one (list+find), render card (or "not found").
- `run_schedule_action` → after the action, re-render the card (delete → deleted card).

`handlers/discord_commands.py`:
- `is_sched_open` → background: resolve email → ensure/reuse private thread (via TasksClient
  thread get/set) → post dashboard in thread → point ephemeral ACK at it.
- `is_sched_select` → `run_schedule_card` (update-in-place, DEFERRED_UPDATE).
- run/pause/resume/del card buttons → DEFERRED_UPDATE → action → edit card in place.
- New/Edit modal flow unchanged except they now run in the thread.

`clients/tasks.py`: `get_user_thread(discord_id)`, `set_user_thread(discord_id, thread_id)`
(internal-secret).

### tasks service (compile-checked)
- `migration 016`: `ALTER TABLE tasks.discord_links ADD COLUMN schedules_thread_id text`.
- `models.DiscordLink.schedules_thread_id`.
- `routes_discord_links.py`: `GET /discord-links/{id}/thread` → `{thread_id}`;
  `POST /discord-links/{id}/thread` `{thread_id}` → store. (X-Internal-Secret.)

## Testing
Pure: `cron_to_human` (table + fallback), `schedule_status_label`, dashboard/select/card
builders, changed entry panel. Router: dashboard/card render + action re-render. Routing:
open→thread+dashboard, select→card, card-action update-in-place. TasksClient thread get/set
(respx). Existing schedule tests updated for the new model (build_schedule_list removed).

## Honest scope
webhook-handler fully TDD'd; tasks migration 016 + endpoints compile-checked, verified on
deploy. Live Discord smoke (open → thread → dropdown → card → actions) needs a deploy.
