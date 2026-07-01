# Everything from chat — design

Date: 2026-07-01
Branch: `feat/just-chat-intent-router`
Status: approved (design), pending implementation
Sub-project 2 of 4 (audit follow-up). Depends on Foundation (shipped). Next: my-workspace, slack-catch-up.

## Problem

The intent router classifies 8 intents but only 3 run end-to-end (build_app,
schedule_task, daily_briefing). The other 5 (make_video, find_jobs,
find_engineers, summarize_email, web_research) fall to `decide()`'s "suggest"
branch, whose copy says "Tap a button below to start" while **no button is
rendered** (audit finding #4). Separately, the welcome/help menu lists only 2 of
~9 capabilities and connectors are undiscoverable.

## Decisions (from brainstorming)

- **Open the real form** for the intents that need structured input
  (make_video, find_jobs, find_engineers): "Yes" opens the existing modal.
- **Defer the on-join greeting** (it needs Discord's privileged Server Members
  Intent + a Slack app-home event subscription — dev-portal/ops config). Instead
  **expand the existing welcome/help menu** to all capabilities now.

## Scope

Make every actionable intent do something real from a plain message:

- **Run on confirm** (no form): `summarize_email` -> `_handle_email`;
  `web_research` -> `_handle_web_search` (query = the detail). (build_app /
  schedule_task / daily_briefing already run — unchanged.)
- **Open the form on confirm**: `make_video`, `find_jobs`, `find_engineers` ->
  open the existing modal. On Discord the confirm interaction returns the modal
  synchronously (a component interaction may respond with a modal); on Slack the
  confirm block-action `views.open`s it with the trigger_id. Reuses the existing
  modal builders and their submit handlers — no new backend flow.

Discoverability:

- Expand the welcome card and `/aiui help` to all capabilities (build a site,
  schedule a task, daily briefing, make a video, find jobs, find engineers,
  summarize email, research) plus a **Connect accounts** (Gmail/Drive) entry.
- Render the action buttons on Slack `/aiui help` too (today Slack help is
  text-only; `_handle_help` gates components off for Slack).

Out of scope (documented follow-ups):

- Auto first-run greeting on Discord member-join / Slack app_home_opened (needs
  a privileged intent + an event subscription; ops-gated).
- Full chat-native collection of video/recruiting inputs (the modal is the form).

## Architecture

Small; reuses the existing confirm-token + modal machinery.

### `handlers/intent_router.py`
- Add `FORM = ("make_video", "find_jobs", "find_engineers")` (pure constant) —
  the intents whose confirm opens a modal instead of running.
- `decide()`: simplify to two outcomes — `question` or below-threshold ->
  `Action("answer", ...)`; any other (actionable) intent -> `Action("confirm",
  ...)`. This drops the "suggest" branch entirely, so every actionable intent
  gets a real confirm button. (`suggest_line` stays for now but is no longer
  emitted by decide; `plan_chat_step`'s suggest branch becomes dead and is
  removed.)

### `handlers/commands.py`
- `run_confirmed_intent`: extend the dispatch — `summarize_email` -> await
  `_handle_email(ctx)`; `web_research` -> set `ctx.arguments = detail` then await
  `_handle_web_search(ctx)`. (build_app/schedule_task/daily_briefing unchanged.)
  FORM intents are NOT run here (the platform layer opens their modal); if one
  reaches here it falls through to a friendly "open it from the panel" line.
- `plan_chat_step` unchanged in shape: the 5 intents are now confirm-class and
  (not being in EXECUTABLE) go straight to a confirm card, exactly like
  daily_briefing does today.

### `handlers/discord_commands.py`
- `_handle_intent_confirm`: after `peek_intent`, if the intent is in `FORM`,
  return the modal synchronously (`{"type": MODAL, "data": <builder(...)>}`)
  using the existing video/recruiting modal builders; else keep today's routing
  (build/schedule -> private thread; others -> run via `run_confirmed_intent`).

### `handlers/slack_interactions.py`
- `_spawn_intent_action`: if the intent is in `FORM`, `views.open` the matching
  Slack modal with the payload's `trigger_id`; else keep today's DM + run.

### `handlers/onboarding.py`
- Expand `welcome_components_discord` / `welcome_blocks_slack` and the help
  content to all capabilities + a Connect entry. Keep it plain-text labels (no
  emoji), matching the project's UI rule.

### `handlers/commands.py::_handle_help`
- Render the capability buttons on Slack too (drop the `platform != "slack"`
  gate for the new menu), so Slack help isn't a dead wall of text.

## Testing

Unit:
- `intent_router.decide`: each actionable intent above threshold -> "confirm"
  (including the 5 previously-suggested ones); `question`/low-confidence ->
  "answer"; decide never returns "suggest".
- `run_confirmed_intent`: `summarize_email` awaits `_handle_email`;
  `web_research` awaits `_handle_web_search` with the detail as the query.
- Discord `_handle_intent_confirm`: a FORM intent returns a `MODAL` response
  (type 9) and does NOT spawn `run_confirmed_intent`.
- Slack `_spawn_intent_action`: a FORM intent calls `views.open` (open_modal),
  not the run path.
- Onboarding builders: the expanded menu includes every capability + Connect;
  Slack help now returns blocks with buttons.

Live in-container e2e (both platforms): "make me a video" -> confirm -> the
video modal opens; "summarize my email" -> confirm -> the email flow runs;
"research X" -> confirm -> the web-search flow runs; the welcome/help menu lists
all capabilities.

## Deploy

Webhook-handler only (no tasks rebuild). Per-file scp; `discord_commands.py` via
the CRLF 3-way merge onto the server's drifted copy (preserve video code);
`commands.py`, `intent_router.py`, `slack_interactions.py`, `onboarding.py`
drift-checked. Never touch `.env`. Verify Up (healthy) + gateway reconnect + an
in-container e2e.
