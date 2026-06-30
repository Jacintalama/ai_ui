# Proactive Daily Assistant — design (sub-project 3 of 3)

**Date:** 2026-06-30
**Status:** design + implementation (autonomous build per user "continue everything").

## Idea

Turn the bot from passive to proactive: a **daily briefing** that reaches out each
morning with what matters — unread email, today's schedule, and anything that
finished overnight. This is Lukas's "do the work for the people" in its simplest
durable form.

## Key realization (reuse, don't rebuild)

Scheduled tasks already exist on both platforms and the scheduler already runs an
arbitrary prompt on a cron and delivers the result back to the channel (via the
`/internal/schedule-result` callback). So a "morning briefing" is just a **daily
schedule with a good briefing prompt** created through the existing
`TasksClient.create_schedule(...)`. No new scheduler, no new delivery path.

## Scope (webhook-handler, testable; no new flag)

1. **A pre-baked briefing.** Pure `daily_briefing_prompt()` + constants
   `DAILY_BRIEFING_NAME = "Daily briefing"`, `DAILY_BRIEFING_CRON = "0 8 * * *"`.
   The prompt is resilient: it asks for an email summary but tells the model to say
   one line if it cannot access email (so it degrades gracefully until the Gmail
   connector is fixed — audit #7, a backend follow-up).
2. **One-tap setup / teardown.** `create_daily_briefing(ctx)` creates the daily
   schedule delivering to `ctx.channel_id` on `ctx.platform`; `remove_daily_briefing
   (ctx)` finds it by name and deletes it. `_handle_briefing(ctx)` routes
   `/aiui briefing` (create) vs `/aiui briefing off` (remove).
3. **Two entry points:**
   - `/aiui briefing` command (parse_command + execute), registered in
     `register_discord_commands.py` so a future deploy exposes the Discord
     subcommand; works on Slack text immediately.
   - The intent router: a new `daily_briefing` intent so plain English ("brief me
     every morning") routes to a confirm card → `create_daily_briefing`. On-vision
     "just chat" path (flag-gated like the rest of the router).

## Out of scope / follow-ups

- **Gmail/Drive connect loop fix (audit #7).** That's a connector + tasks-service
  concern; the briefing's email line degrades gracefully without it. Noted, not
  built here.
- A welcome-card "Daily briefing" button (would change the onboarding cards + their
  exact-count tests). Deferred; the command + intent cover discovery for v1.
- Per-user timezone (uses the schedule default Asia/Manila).

## Tests

- `daily_briefing_prompt()` mentions email + today.
- `create_daily_briefing` calls `create_schedule` with the right name/cron/prompt
  and the ctx delivery target; posts a friendly confirmation.
- `/aiui briefing off` lists schedules, deletes the one named "Daily briefing".
- intent router: `decide(daily_briefing)` is "confirm"; a confirmed `daily_briefing`
  intent calls `create_daily_briefing`.

## Done when

`/aiui briefing` (and "brief me every morning" via the router) sets up a daily
schedule that the existing scheduler runs and delivers — full suite green. Live
verification waits for deploy (per the user's "test later").
