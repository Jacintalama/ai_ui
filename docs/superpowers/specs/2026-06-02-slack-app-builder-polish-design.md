# Slack App Builder — UX Polish + Private DM Spaces + Full Parity

**Date:** 2026-06-02
**Status:** Design (approved in brainstorming; pending spec review + user review)
**Repo:** Jacintalama/ai_ui · service: `webhook-handler`

## Summary

The Slack bot is live with App Builder basics (template-button panel → modal →
build → preview link, all posted into the shared `#app-builder` channel). This
work brings Slack to full Discord App Builder parity and polish:

1. **Polish** — replace the template button grid with a dropdown ("Pick a
   template…"), and render clean Block Kit cards with a color-bar accent and
   plain-text labels.
2. **Private per-user space** — each build conversation happens in a **DM** with
   the user (the Slack analog of Discord's private per-user thread), so
   `#app-builder` only ever shows the panel.
3. **Full functional parity** — after a build, a card with **Publish / Enhance /
   Open preview** buttons; `/aiui aiuibuilder list` shows the user's apps with
   per-app **Status / Publish / Enhance / Unpublish** buttons.
4. **MCP** — already works on Slack via `/aiui mcp <server> <tool> [json]`
   (shared MCP Proxy); no code change, verified live during testing.

### Decisions (from brainstorming)

- Private space mechanism: **Direct message** (chosen over in-channel thread or
  ephemeral messages — only DM is both private and able to carry multi-minute
  build progress).
- Parity scope: **full**, including interactive Publish/Enhance/Unpublish/Status
  buttons (not slash-only management).
- MCP: **confirm only** (no new MCP UI; matches Discord, which is also slash/chat).
- Architecture: **Approach A** — reuse the platform-agnostic business logic
  (`CommandRouter.run_panel_build`, `TasksClient`); add a Slack-only presentation
  + routing layer. No changes to Discord handlers or `CommandRouter` business
  logic. (Rejected Approach B: refactor the router to be UI-agnostic — higher
  regression risk to the live Discord flows for little near-term gain.)

## Architecture

Business logic stays shared and untouched; Slack gets presentation + routing only.

- **`clients/slack.py`** (extend): `open_dm(user_id) -> channel_id`
  (`conversations.open`) and `post_ephemeral(channel, user, text)`
  (`chat.postEphemeral`). Existing `post_message`, `open_modal`,
  `get_user_email` unchanged.
- **`handlers/slack_app_builder_panel.py`** (extend, pure Block Kit, no I/O):
  - `build_panel_blocks(templates)` → rebuilt as a `static_select` dropdown
    ("Pick a template…", one option per template) + a Blank button. No template
    truncation (static_select allows ≤100 options).
  - `build_ready_blocks(slug, preview_url)` → result card + Publish / Enhance /
    Open-preview buttons, green color-bar attachment.
  - `build_published_blocks(slug, public_url)` → published card + Enhance /
    Unpublish / Open buttons, blue color-bar attachment.
  - `build_apps_list_blocks(apps)` → one section row per app with state-aware
    buttons (draft → Publish; published → Unpublish; always Status/Enhance).
  - `build_enhance_modal_view(slug)` → modal with one multiline input.
  - action_id / callback_id constants + parsers for: template select, Publish,
    Enhance (button + modal), Unpublish, Status. Each carries the slug; parsers
    round-trip it and reject wrong-prefix ids cleanly.
- **`handlers/slack_interactions.py`** (extend): route new `block_actions`
  (template select, Publish, Enhance, Unpublish, Status) and `view_submission`
  (build modal, enhance modal). Opens the DM, renders cards there, reuses
  `run_panel_build` for build+watch, and calls `TasksClient` directly for
  publish/unpublish/enhance/status/list rendering.
- **`handlers/slack_commands.py`** (small): `/aiui aiuibuilder list` renders the
  Block Kit app list via the new builder.
- **No changes** to `handlers/commands.py` business logic, `main.py` routes, or
  any Discord handler.
- **Ops:** add bot scope **`im:write`** + reinstall the Slack app.

### Reused data layer (TasksClient — already present)

`list_projects`, `get_project_status`, `start_build`, `get_build_status`,
`list_templates`, `publish_app`, `unpublish_app`, `enhance_app`. The Slack layer
calls these for data and renders Block Kit; `run_panel_build` is reused wholesale
for the build+watch+notify lifecycle (it already drives delivery through the
`CommandContext` callbacks).

## Data flow

### A) Build (private-DM journey)

1. `#app-builder`: user selects a template from the dropdown (or clicks Blank) →
   `block_actions` → `views.open` with the description modal. The originating
   channel id is carried in the modal's `private_metadata`.
2. Modal submit → `view_submission`:
   - `open_dm(user)` → DM channel id.
   - `post_ephemeral` in `#app-builder`: "Starting your build — sent to your DMs."
   - Post "Building `<slug>`…" into the DM.
   - Build a `CommandContext` whose `respond`, `notify_channel`, and
     `notify_channel_rich` all target the DM channel; fire
     `run_panel_build(ctx, template_key, description)` as a background task.
   - Return `{}` (closes the modal within Slack's 3s window).
3. On completion, `run_panel_build` calls `ctx.notify_channel_rich(...)` → Slack
   closure renders `build_ready_blocks` into the DM.

### B) Build-ready card actions (in the DM)

- Open preview → link button (URL only).
- Publish → `publish_app(email, slug)` → render `build_published_blocks`.
- Enhance → enhance modal → submit → `enhance_app(email, slug, prompt)` /
  `run_panel_enhance` → progress + refreshed card in the DM.
- Unpublish → `unpublish_app(email, slug)` → refreshed card.

### C) App list / management

`/aiui aiuibuilder list` → `list_projects(email)` → `build_apps_list_blocks`.
Per-app buttons reuse the same `block_actions` handlers as the build-ready card
(slug carried in the action_id), and their responses also land privately.

### Identity

Email resolved via the existing `_resolve_email_for_ctx` (Slack → `users.info`,
needs `users:read.email`). If unresolved, the bot replies with the clear
"ask an admin to grant `users:read.email`" message and does not build.

## Block Kit layouts

- **Panel:** header section + `static_select` ("Pick a template…", option per
  template) + Blank button.
- **Build-ready card (DM):** green color-bar attachment; section
  "Build ready: `<slug>`"; actions row Publish / Enhance / Open preview (link).
- **Published card (DM):** blue color-bar attachment; "Published: `<slug>`" +
  live URL; actions Enhance / Unpublish / Open (link).
- **App list:** one section per app (`<slug> — <state>`) + state-aware buttons,
  capped at a sensible number of rows; overflow note points to
  `/aiui aiuibuilder status <slug>`.
- **Modals:** description modal (template picked) and enhance modal — title ≤24
  chars, one multiline `plain_text_input`, `private_metadata` ≤3000 carrying
  channel id + slug.
- Plain-text labels (no emoji/icons, per user preference); color conveyed only
  via the attachment color bar.

## Error handling

Every path degrades gracefully — no dead-ends, no 500s.

- **DM open fails** (user has DMs off, etc.): fall back to a private
  `post_ephemeral` card in `#app-builder`; log it. No public channel post.
- **Email unresolved:** scope-hint message; no build attempt.
- **TasksClient/API error or service down:** caught; terse plain-text failure in
  the DM (e.g., "Build failed — <reason>. Try /aiui aiuibuilder status <slug>.").
  The build watcher already runs detached with guards.
- **3-second ACK:** all interactions ack/close immediately; slow work runs in a
  background task and reports back into the DM (mirrors Discord fire-and-forget).
- **Double-clicks / stale buttons:** publish/unpublish are idempotent against
  current state; unknown/old action_ids are a harmless no-op, never an error.
- **Signature:** all interactions continue through the live HMAC
  `verify_slack_signature`.
- **Block Kit limits** respected (title ≤24, private_metadata ≤3000, ≤5 buttons
  per row, ≤100 dropdown options).

## Testing

pytest + pytest-asyncio; mocked Slack client + TasksClient; `await
asyncio.sleep(0)` to drain fire-and-forget; no live network.

- **Builders/parsers** (`test_slack_panel.py`): dropdown has all templates +
  Blank; build-ready/published cards have correct state-aware buttons, color
  bar, slug-encoded action_ids, link buttons carry URLs; app-list rows are
  state-aware; parsers round-trip slug and reject wrong prefixes; enhance modal
  shape.
- **Interaction routing** (`test_slack_interactions.py`): template select →
  views.open; build modal submit → open_dm + channel ephemeral + run_panel_build
  with DM-targeted ctx + returns `{}`; completion → build-ready card in DM;
  Publish/Enhance/Unpublish/Status → correct TasksClient calls + rendering;
  error paths (DM-open fail → ephemeral fallback; email unresolved → scope hint;
  TasksClient error → terse message, no raise).
- **Slash** (`test_slack_command_build_notify.py` / new): `/aiui aiuibuilder
  list` → list_projects → app-list blocks.
- **Client** (`test_slack_client_modal.py`): `open_dm` calls conversations.open
  and returns the channel id; `post_ephemeral` shape.
- **Gate:** full webhook-handler suite stays green (currently 390 passing);
  Discord tests untouched.

## Out of scope

- Cron/Schedules UI for Slack (Discord-only; explicitly deferred).
- Any MCP UI beyond the existing slash command.
- Changes to the Discord App Builder or the shared `CommandRouter` business logic.

## Operator setup (post-implementation)

1. api.slack.com/apps → AIUI → OAuth & Permissions → add bot scope `im:write` →
   Reinstall to Workspace.
2. Deploy webhook-handler (per CLAUDE.md manual scp/archive + rebuild).
3. Re-run `scripts/setup_slack_app_builder_channel.py` if the panel needs the new
   dropdown layout re-posted.
4. Verify: dropdown build → DM card → Publish/Enhance; `/aiui aiuibuilder list`;
   `/aiui mcp <server> <tool>`.
