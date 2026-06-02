# Slack App Builder Parity — Design

**Date:** 2026-06-01
**Status:** Approved (full parity, one-shot implementation)
**Branch:** `feat/vm-agent-flight-mcp`

## Goal

Bring the Slack bot to 100% feature parity with the Discord bot: AI chat,
all `/aiui` commands, the App Builder build flow, **and** the clickable
template panel (buttons → modal → build). Everything must work and the local
test suite must be green. Deploy happens once the Hetzner IP is unblocked.

## Existing state (reused as-is)

- `clients/slack.py` — HMAC-SHA256 signature verify, `post_message`,
  `post_to_response_url`, `format_ai_response`.
- `handlers/slack.py` — @mention + DM → OpenWebUI chat (the "AI UI chat").
- `handlers/slack_commands.py` — `/aiui` slash command → `CommandRouter`.
- `main.py` routes `/webhook/slack`, `/webhook/slack/commands`; client init.
- `CommandRouter` — `ask` / `mcp` / `aiuibuilder` / etc. already
  platform-agnostic (branches on `ctx.platform` only for output limits).
- `Caddyfile` — `/webhook/*` → `webhook-handler:8086`.

## The four gaps to parity

### A. Email resolution (decided: auto via Slack API)

The App Builder tags each build to a user email. Discord uses the static
`DISCORD_USER_EMAIL_MAP`. Slack will resolve the email at call time via the
Slack Web API `users.info` (profile email), requiring the `users:read.email`
scope on the Slack app. No env map to maintain.

- New `SlackClient.get_user_email(user_id)` — GET `users.info`, return
  `user.profile.email` or `None`; never raises.
- New `CommandRouter._resolve_email(ctx)` — `slack` → `get_user_email`,
  otherwise the Discord map. New `_not_linked_message(ctx)` — platform-aware
  copy (Discord keeps the exact "isn't linked" string the test suite asserts;
  Slack gets a "ask an admin to grant `users:read.email`" message).
- Three call sites updated: `_handle_cronjob`, `_handle_aiuibuilder`,
  `run_panel_build`.

### B. Slash-command build notifier

`_start_build` only starts the result watcher when `ctx.notify_channel` is set.
The Slack slash handler currently sets only `respond` (ephemeral via
`response_url`). Add a `notify_channel` that posts to the channel via the bot
token (`chat.postMessage`), so the "ready" link is delivered after the build —
mirroring Discord's bot-token channel post that outlives the interaction window.

### C. Clickable template panel (the new piece)

- New pure module `handlers/slack_app_builder_panel.py` (Block Kit analog of
  `app_builder_panel.py`): `build_panel_blocks(templates)` (section + actions
  blocks, ≤5 buttons/block, ≤25 buttons, always a Blank button),
  `build_modal_view(template_key, label, channel_id)` (modal view; `callback_id`
  carries the template key; `private_metadata` carries the channel id so the
  submit knows where to post), and the `is_panel_button` / `is_panel_modal` /
  `template_key_from_*` parsers. Same `aiuibuild:tpl:` / `aiuibuild:build:`
  prefixes as Discord for consistency.
- New `SlackClient.open_modal(trigger_id, view)` — POST `views.open`.
- New handler `handlers/slack_interactions.py` — routes Slack interactivity:
  `block_actions` (button click) → `open_modal`; `view_submission` (modal
  submit) → build a `slack` `CommandContext` (respond + notify_channel both
  post to the channel from `private_metadata`) and fire-and-forget
  `router.run_panel_build`. Unknown action/callback → harmless empty 200.
- New route `POST /webhook/slack/interactions` in `main.py` (Slack sends
  `payload=<json>` form-encoded; verify signature, json-load, dispatch).

### D. One-shot setup script

New `scripts/setup_slack_app_builder_channel.py` (Slack analog of
`setup_app_builder_channel.py`): fetch templates from tasks, find-or-create the
`#app-builder` channel (`conversations.list` / `conversations.create` /
`conversations.join`), post the Block Kit panel (`chat.postMessage`), pin it
(`pins.add`). Idempotent.

## Data flow

- **Chat:** unchanged (`handlers/slack.py`).
- **Build via slash:** `/aiui aiuibuilder build "<desc>"` → ephemeral ack →
  `_resolve_email` → `start_build` → watcher → channel post with link.
- **Build via panel:** pinned buttons → `block_actions` → `views.open` modal
  (`private_metadata=channel_id`) → `view_submission` → empty 200 (closes
  modal) + fire-and-forget `run_panel_build` → channel posts "Building…" then
  the link.

## Error handling

- Bad/missing Slack signature → 401 (existing pattern; applies to the new
  interactions route too).
- `users.info` failure / no profile email → friendly Slack message naming the
  `users:read.email` scope. No silent failure.
- Build API errors → existing `_format_build_error`.
- All Slack API calls wrapped in try/except; log and degrade, never crash the
  handler. `open_modal` / `post_message` return bool/None on failure.

## Testing (local, must be green)

New: `test_slack_panel.py` (blocks, parsers, modal view: callback_id +
private_metadata), `test_slack_interactions.py` (button→open_modal,
submit→run_panel_build with channel from private_metadata, unknown noop),
`test_slack_email_resolution.py` (`get_user_email` happy/no-email/error via
respx; `_resolve_email` slack vs discord), `test_slack_command_build_notify.py`
(slash build sets notify_channel that posts to the channel),
`test_slack_client_modal.py` (`open_modal` → `views.open`),
`test_setup_slack_script.py` (find/create/post/pin flow via respx).
Existing Discord suite must stay green.

## Operator setup (not code)

Slack app scopes: `chat:write`, `commands`, `app_mentions:read`, `users:read`,
`users:read.email`. Enable Interactivity (request URL
`…/webhook/slack/interactions`), Event Subscriptions (`…/webhook/slack`), and
the `/aiui` slash command (`…/webhook/slack/commands`). Set `SLACK_BOT_TOKEN`
and `SLACK_SIGNING_SECRET` in the server `.env`. Run the setup script once to
post the panel. Requires the Hetzner IP unblocked (Slack must reach the public
URL to verify the request URLs).
