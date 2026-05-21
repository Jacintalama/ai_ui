# Discord App Builder Channel — Design

**Date:** 2026-05-21
**Status:** Approved (pending spec review)
**Topic:** A dedicated Discord channel where users build apps by clicking colored
template buttons and filling a popup form — no slash commands typed.

## Problem

Today, building an app from Discord means typing
`/aiui aiuibuilder build <template> <description>` in any channel. The user wants
a dedicated `#app-builder` channel with a friendly, click-driven panel: pick a
template (a colored button), a popup form opens, type the app idea, submit — and
the bot posts the live URL in the channel when the build finishes.

## Goals

- A pinned **panel** in a dedicated channel with one **colored button per
  template** (green/blue) plus a **Blank** button.
- Clicking a button opens a **modal** (popup form) with a single "Describe your
  app" field. No commands typed.
- Submitting starts the build and posts progress + the final URL in the channel.
- **Reuse the entire existing `aiuibuilder` backend** (`TasksClient.start_build`,
  the build watcher, the email-link check). No new infrastructure.

## Non-goals

- The Open WebUI right-side prompt panel — explicitly out of scope (separate task).
- A gateway/"message content" bot that treats plain messages as builds — rejected
  in favor of buttons+modals (no privileged intent, no extra process).
- New tables, new build pipeline, or changes to how builds actually run.

## Key architectural fact

Discord delivers **buttons (message components) and modals to the SAME
interactions endpoint** that already handles slash commands
(`POST /webhook/discord`), with the **same Ed25519 signature**. So no new route,
no new auth, no gateway. We only teach the existing
`DiscordCommandHandler.handle_interaction` two more interaction types.

The live template catalog comes from the existing
`GET /api/aiuibuilder/templates` (auth = any `X-User-Email`). It **excludes
`blank`/`custom`** (those are template-less builds), returning **17 templates**.
So the panel = 17 template buttons + 1 Blank button = **18 buttons** (Discord
caps buttons at 5/row, 25 total — 18 fits in 4 rows).

## Components

### 1. `webhook-handler/handlers/app_builder_panel.py` (new, pure functions)

Single source of truth for the panel/modal JSON and custom_id scheme. Pure
(no I/O) so both the setup script and the interaction handler import it, and it
is fully unit-testable.

- `CUSTOM_ID_PREFIX = "aiuibuild:tpl:"` — button custom_id is `aiuibuild:tpl:<key>`
  (`<key>` empty for Blank).
- `MODAL_PREFIX = "aiuibuild:build:"` — modal custom_id is `aiuibuild:build:<key>`.
- `build_panel_payload(templates: list[dict]) -> dict` — returns
  `{"content": <blurb>, "components": [<action rows>]}`. One button per template
  (style alternates **green=3 / blue=1**), label `"<emoji> <label>"` (≤80 chars),
  custom_id `aiuibuild:tpl:<key>`; plus a trailing **Blank** button (style grey=2,
  custom_id `aiuibuild:tpl:`). Lays out 5 buttons/row, ≤5 rows.
- `build_modal_payload(template_key: str, template_label: str | None) -> dict` —
  returns the `data` for a type-9 MODAL response: title, custom_id
  `aiuibuild:build:<key>`, one paragraph TEXT_INPUT (`custom_id="description"`,
  label "Describe your app", required, max 4000).
- `parse_template_key(custom_id, prefix) -> str | None` — returns the key, or
  `None` for the Blank/empty key. Returns sentinel/`None` for non-matching ids.

### 2. `webhook-handler/handlers/discord_commands.py` (extend)

Add interaction-type dispatch in `handle_interaction`:
- `MESSAGE_COMPONENT (type 3)` → `_handle_message_component`: parse the button
  custom_id. If it's ours, respond **synchronously** with a MODAL
  (`{"type": 9, "data": build_modal_payload(...)}`). Modals must be the immediate
  response to a component — cannot defer first. Unknown custom_id → safe no-op
  (`{"type": 6}` DEFERRED_UPDATE_MESSAGE, no visible change).
- `MODAL_SUBMIT (type 5)` → `_handle_modal_submit`: parse modal custom_id for the
  template key; extract the description from
  `data.components[0].components[0].value`; resolve the submitting user/channel;
  build a `CommandContext` (`respond` = `edit_original` on the modal token,
  `notify_channel` = `post_channel_message(channel_id)`); fire-and-forget
  `asyncio.create_task(router.run_panel_build(ctx, key, description))`; return
  `{"type": 5}` (deferred ACK) immediately — mirroring the slash-command flow.

New interaction-type constants: `MESSAGE_COMPONENT = 3`, `MODAL_SUBMIT = 5`.
New callback-type constants: `MODAL = 9`, `DEFERRED_UPDATE_MESSAGE = 6`.
(Note: interaction type 5 = MODAL_SUBMIT and callback type 5 = deferred-channel
share the number but live in different fields — commented in code.)

### 3. `webhook-handler/handlers/commands.py` (refactor + new method)

- **Extract** `_start_build(ctx, email, template_key, description, *,
  template_label=None)` from the inline build code currently inside
  `_handle_aiuibuilder`'s `build` branch. It calls `tasks_client.start_build`,
  responds `"Building \`slug\`…"`, and wires the result watcher
  (`_watch_build`). The `build` branch calls this after its text parsing — its
  behavior is unchanged (covered by existing `test_aiuibuilder_build.py`).
- **New** `run_panel_build(ctx, template_key, description)` — the panel entry
  point. Resolves email from `self._discord_user_email_map`; if unlinked →
  responds "isn't linked"; if description blank → responds usage; otherwise calls
  `_start_build`. Passing the key **explicitly** (not via free-text re-parsing)
  avoids the edge where a Blank build whose first word equals a template key would
  be misread as a template build.

### 4. `scripts/setup_app_builder_channel.py` (new, one-shot, modeled on `register_discord_commands.py`)

- Reads env: `DISCORD_BOT_TOKEN` (req), `DISCORD_GUILD_ID` (req), `TASKS_URL`,
  `APP_BUILDER_SETUP_EMAIL` (email used only to fetch the catalog; default first
  of `ADMIN_EMAILS`), `APP_BUILDER_CHANNEL_NAME` (default `app-builder`).
- Steps: (1) `GET {TASKS_URL}/api/aiuibuilder/templates` with `X-User-Email` →
  templates; (2) list guild channels, reuse the channel if one with that name
  exists, else `POST /guilds/{guild}/channels` (type 0 text); (3) build the panel
  via `build_panel_payload`; (4) `POST /channels/{id}/messages`; (5) pin it
  (`PUT /channels/{id}/pins/{message_id}`); (6) print channel + message IDs.
- Idempotent: re-running reuses the channel and posts a fresh (re-pinned) panel.
- Clear errors on missing env, unreachable tasks service, or missing bot perms
  (needs **Manage Channels** + **Send Messages**).

## Data flow

```
User clicks "🟢 Portfolio"
  → Discord POST /webhook/discord  {type:3, data.custom_id:"aiuibuild:tpl:portfolio"}
  → handler returns {type:9, data: modal "Describe your app"}   (popup opens)
User types "a portfolio for Maya, a UX designer" + Submit
  → Discord POST /webhook/discord  {type:5, data.custom_id:"aiuibuild:build:portfolio",
       data.components[0].components[0].value:"a portfolio for Maya..."}
  → handler returns {type:5} (deferred) and create_task(router.run_panel_build(
       ctx, "portfolio", "a portfolio for Maya..."))
  → run_panel_build → _start_build → TasksClient.start_build(email, desc,
       template_key="portfolio") → "Building `portfolio-maya-ab12`…"
  → _watch_build polls get_build_status → posts the live URL to the channel
```

## Error handling

- Unknown / non-matching component custom_id → `{"type": 6}` no-op (never 500).
- Modal submit with empty description → `run_panel_build` responds usage text.
- Unlinked Discord user → "isn't linked" (existing copy), via the deferred edit.
- `TasksAPIError` (429 build-in-progress, 0 unreachable, 401/403, 4xx) → reuses
  the existing `_format_build_error` copy.
- Watcher failures never crash (existing `_watch_build` swallows notify errors).

## Testing (TDD)

`webhook-handler/tests/test_app_builder_panel.py`:
- `build_panel_payload`: ≤5 rows, ≤5 buttons/row; one button per template + Blank;
  custom_ids `aiuibuild:tpl:<key>`; styles green/blue; Blank present & grey.
- `build_modal_payload`: type-9 data, custom_id `aiuibuild:build:<key>`, a
  paragraph text input `description`.
- Component interaction (type 3, `aiuibuild:tpl:portfolio`) →
  `handle_interaction` returns `{type:9}` with modal custom_id
  `aiuibuild:build:portfolio`.
- Unknown component custom_id → `{type:6}` no-op.
- Modal submit (type 5) → returns `{type:5}` AND awaited `router.run_panel_build`
  called with (`"portfolio"`, the description) and `ctx.user_id` = submitter.
- Blank modal submit (`aiuibuild:build:`) → `template_key=None`.

`webhook-handler/tests/test_panel_build.py` (router, mirrors `test_aiuibuilder_handler.py`):
- unmapped user → "isn't linked"; empty description → usage.
- happy path → `tasks_client.start_build(email, desc, template_key=...)` called,
  responds "Building `slug`…", watcher started when `notify_channel` set.

Regression: existing `test_aiuibuilder_build.py` and `test_aiuibuilder_handler.py`
must stay green after the `_start_build` extraction.

## Definition of "green, end to end"

- The full webhook-handler + tasks test suites pass (no reds).
- The feature is complete and runnable.
- **Going live** (run once on the server where the bot + webhook-handler run):
  `DISCORD_GUILD_ID=<id> python scripts/setup_app_builder_channel.py`, after the
  updated webhook-handler is deployed (so the interactions endpoint handles
  buttons/modals). Buttons reuse the already-configured interactions URL; if
  slash commands work today, buttons will once deployed. This deploy + the live
  run are the user's final step; exact commands provided at hand-off.
