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
- **Discord (`commands.py`):** ALL **7** `list_schedules` call sites must pass `platform="discord"` (reviewer-enumerated): lines **1309** (`cronjob list` text), **1683** (`run_schedule_list`), **1811** (get-schedule-for-edit), **1830** (`dashboard_payload`), **1842** (`run_schedule_card`), **1917** (`run_cron_list`), **1933** (`_cron_menu_for`). Missing any (esp. 1309/1917/1933) lets a Slack schedule leak into Discord views. (Discord create omits `delivery_platform` and relies on the tasks default `"discord"` — that's already correct; do NOT change it.)
- Net: Slack shows only Slack schedules (and Run-now on them delivers to the Slack DM, since their stored platform is slack); Discord shows only Discord ones. The user's existing Discord schedule stays in Discord; Slack shows "no schedules yet" until one is created on Slack.

### 2. Human time on the Slack card
- **`slack_schedule_panel.py build_schedule_card`:** render the time via `cron_to_human(sched["cron_expr"])` (import from `schedule_format`) — e.g. "every day at 9:41 PM". Drop the raw `41 21 * * *` from the visible card (optionally keep it only in an edit context). Apply the same to `build_schedules_dashboard` rows if they show the cron.

### 3. Minimalist result output (webhook-handler `main.py`)
- **`_format_schedule_result(name, status, result)`** → clean & quiet. NOTE `name` differs by platform: Discord = `"<when>: <prompt>"` (splits on the first `": "` → title=prompt, footer=when); **Slack = bare prompt only** (no `": "`, no when). So:
  - completed: `**{title}**\n\n{body}` and, only if a `when` was split out (Discord), append `\n\n_{when}_`. The bare-prompt (Slack) case — title = `name`, no footer — is the EXPECTED path, not an edge case. No ✅ emoji.
  - skipped/failed: prefix a subtle `⚠️ ` + a one-word status; keep the body.
  - Keep the ≤1990-char cap. Never raise — fall back to the raw body if splitting fails.

### 4. Clean agent formatting (tasks `scheduler.py`)
- An OUTPUT STYLE directive ALREADY exists in `_create_task_from_schedule` at **line ~159** ("Produce clear, concise… do NOT add ASCII boxes/banners…"). **EDIT that line in place — do NOT append a second, competing directive.** Keep the "delivered inside a branded card / no ASCII boxes" constraint and fold in: "format minimally — a short bold title, then the content, then at most one brief line of context; minimal emoji." This shapes the agent's answer (the "Quote of the Day / Why it lands today" sprawl) into a tidy, consistent structure.

## Error handling / compatibility
- `platform` filter omitted ⇒ returns all (existing callers unaffected; Discord default behavior preserved if a call site isn't updated).
- A schedule with no/unknown `delivery_platform` defaults to `discord` (existing rows) — so it shows in Discord, not Slack. Correct.
- Result formatter must never raise; fall back to the raw body if name-splitting fails.

## Testing (TDD)
- **tasks:** `GET /schedules?platform=slack` returns only slack rows; no param returns all. List output includes `delivery_platform`.
- **client:** `list_schedules(email, platform="slack")` sends `?platform=slack`.
- **Slack:** open dashboard fetches with `platform="slack"`; card shows `cron_to_human` text, not raw cron.
- **Discord:** list fetches with `platform="discord"` — incl. a test that a Slack schedule does NOT appear in `run_cron_list` / `_cron_menu_for`.
- **cron_to_human** outputs like "every day at 8:00 PM" (align test expectations to the real formatter, not abbreviated forms).
- **`_format_schedule_result`:** completed → no ✅, has title + body; failed → has ⚠️; long output truncated ≤1990.
- **scheduler:** `_create_task_from_schedule` description contains the formatting directive.

## Scope guard (YAGNI)
- No Sync toggle / Settings button / cross-platform fan-out (Ship 2).
- No change to cron parsing, execution, or the scheduler tick.
- Don't restyle the confirm/dashboard buttons beyond the time text.

## Out of scope (→ Ship 2)
- Email-keyed user settings store, Sync on/off, delivering one run to both Slack + Discord, resolving both channels by email.
