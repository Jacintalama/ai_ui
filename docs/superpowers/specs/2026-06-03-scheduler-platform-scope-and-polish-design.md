# Scheduler: Platform-Scoped Schedules + Output Polish (Ship 1)

**Date:** 2026-06-03
**Status:** Design — approved in brainstorming, pending spec review

## Problem (observed)
- A schedule created in Discord delivers to Discord even when opened/Run-now'd from Slack (schedules are shared by email). User expects: **Slack cron → Slack only; Discord cron → Discord only.**
- The Slack schedule card shows the **raw cron** `41 21 * * *` instead of a human time.
- The scheduled-task **result message** is cluttered (`✅ Scheduled task — <when>: <prompt>` + the agent's free-form structure).

## Goal (Ship 1)
1. **Platform-scoped schedules** — Slack lists/creates/runs only `delivery_platform='slack'` schedules; Discord only `'discord'`. (Default; no cross-platform sync — that's Ship 2.)
2. **Human time** on the Slack schedule card (reuse `cron_to_human`).
3. **Minimalist result output** (clean & quiet) + a **clean agent-formatting directive**.

(Ship 2, separate: an email-keyed **Sync** setting + a **Settings** button to deliver to both platforms. Out of scope here.)

## Approved decisions
- Default delivery is platform-scoped by the platform the schedule was created on (already stored as `delivery_platform`).
- Email is the cross-platform identity (relevant to Ship 2's sync).
- Output style: **clean & quiet** (few/no emojis, plain bold header, whitespace; subtle ⚠️ only on failure).

## Changes

### 1. Platform-scoped listing (tasks + both bots)
- **tasks `routes_schedules.py`:** the schedule **list output** must include `delivery_platform` (the create input already has it; confirm the GET serialization includes it — add if missing). Add an optional `platform` query param to `GET /schedules` that filters `WHERE delivery_platform = :platform` when provided (omitted = all, backward compatible).
- **webhook-handler `clients/tasks.py`:** `list_schedules(user_email, platform: str | None = None)` → passes `?platform=` when set.
- **Slack (`slack_interactions.py`):** every schedule list fetch (open dashboard, post-action re-render) calls `list_schedules(email, platform="slack")`.
- **Discord (`commands.py`):** the schedule list fetches (`run_schedule_list`, the dashboard builder, card lookups) call `list_schedules(email, platform="discord")`.
- Net: Slack shows only Slack schedules (and Run-now on them delivers to the Slack DM, since their stored platform is slack); Discord shows only Discord ones. The user's existing Discord schedule stays in Discord; Slack shows "no schedules yet" until one is created on Slack.

### 2. Human time on the Slack card
- **`slack_schedule_panel.py build_schedule_card`:** render the time via `cron_to_human(sched["cron_expr"])` (import from `schedule_format`) — e.g. "every day at 9:41 PM". Drop the raw `41 21 * * *` from the visible card (optionally keep it only in an edit context). Apply the same to `build_schedules_dashboard` rows if they show the cron.

### 3. Minimalist result output (webhook-handler `main.py`)
- **`_format_schedule_result(name, status, result)`** → clean & quiet:
  - completed: `**{task_title}**\n\n{body}\n\n_{when}_` where `task_title`/`when` are derived from `name` (the schedule's name carries the prompt + when; split sensibly, else just show `name` as the title and omit the footer). No ✅ emoji.
  - skipped/failed: prefix a subtle `⚠️ ` + a one-word status; keep the body.
  - Keep the ≤1990-char cap.

### 4. Clean agent formatting (tasks `scheduler.py`)
- In `_create_task_from_schedule`, append a short **output-formatting directive** to the composed description, e.g.:
  > "When you reply, format it cleanly and minimally for a chat message: a short bold title, then the content, then at most one brief line of context. No decorative separators or banners, minimal emoji."
  This shapes the agent's answer (the "Quote of the Day / Why it lands today" sprawl) into a tidy, consistent structure.

## Error handling / compatibility
- `platform` filter omitted ⇒ returns all (existing callers unaffected; Discord default behavior preserved if a call site isn't updated).
- A schedule with no/unknown `delivery_platform` defaults to `discord` (existing rows) — so it shows in Discord, not Slack. Correct.
- Result formatter must never raise; fall back to the raw body if name-splitting fails.

## Testing (TDD)
- **tasks:** `GET /schedules?platform=slack` returns only slack rows; no param returns all. List output includes `delivery_platform`.
- **client:** `list_schedules(email, platform="slack")` sends `?platform=slack`.
- **Slack:** open dashboard fetches with `platform="slack"`; card shows `cron_to_human` text, not raw cron.
- **Discord:** list fetches with `platform="discord"`.
- **`_format_schedule_result`:** completed → no ✅, has title + body; failed → has ⚠️; long output truncated ≤1990.
- **scheduler:** `_create_task_from_schedule` description contains the formatting directive.

## Scope guard (YAGNI)
- No Sync toggle / Settings button / cross-platform fan-out (Ship 2).
- No change to cron parsing, execution, or the scheduler tick.
- Don't restyle the confirm/dashboard buttons beyond the time text.

## Out of scope (→ Ship 2)
- Email-keyed user settings store, Sync on/off, delivering one run to both Slack + Discord, resolving both channels by email.
