# Discord App Builder — Enhance + Unpublish — Design

**Date:** 2026-05-21
**Status:** Approved (pending spec review)
**Topic:** Round out the Discord app builder to match the web one: an **Enhance**
button (type a change → AI edits the existing app → updated preview) and an
**Unpublish** button (take a live app offline). Both via button + popup form,
matching the existing Build/Publish flow.

## Problem

The Discord app builder can build, preview, and publish — but you can't **edit**
an app after building it, and you can't **take it offline** after publishing.
The web app builder has both (the right-side "Enhance" chat, and a
Publish/Unpublish toggle). The user wants the same on Discord, kept simple.

## Goals

- **Enhance:** a button on the app's message → popup "What do you want to
  change?" → the AI edits the *existing* app (same slug) → bot posts the updated
  preview. One change at a time (no multi-turn chat).
- **Unpublish:** a button on the published message → removes the live mapping →
  app goes offline.
- Reuse the publish feature's patterns end to end (user-scoped endpoint +
  button/modal dispatch + the build watcher). No new infrastructure.

## Non-goals (keep it simple / can't-do)

- The web **element picker ("select")** — it requires clicking an element in a
  live browser preview; Discord has no canvas, so it can't be reproduced. Its
  purpose (targeted edits) is served by describing the change in the popup. **Out
  of scope, by necessity.**
- Multi-turn reply-in-channel chat, file/image attachments on enhance, custom
  domains, project delete.

## Key facts (verified)

- **Unpublish** exists admin-only: `DELETE /api/projects/{slug}/publish`
  (`routes_projects.unpublish_app`) — owner check → delete the `PublishedApp`
  row → 204. Idempotent (no row → 204 no-op).
- **Enhance** exists admin-only: `POST /api/tasks/enhance` — takes
  `source_task_id` + `prompt` (+ optional files/selection). It role-checks
  `editor`, advisory-locks per slug, **rejects a concurrent enhance with 409**,
  and creates a new BUILD `TaskItem` with
  `description="Enhance apps/<slug>/: <prompt>"`, `plan_status="approved"`,
  `built_app_slug=<slug>`, then spawns `_run_execution`. The
  `"Enhance apps/<slug>/: "` description prefix is what makes the executor use
  `build_enhance_prompt` (edit-in-place, no new slug).
- The Discord build **watcher** (`CommandRouter._watch_build`) already polls
  `get_build_status(task_id)` and posts the preview link + buttons on
  completion. An enhance produces the same shape (a BUILD task, same slug,
  `preview_url`), so the watcher is reused unchanged.
- A Discord-built app's owner is the build assignee (auto-added owner; also
  implicit-owner via `_require_role`). `editor`/`owner` both pass the enhance
  role check.

## Components

### 1. Tasks service — two user-scoped endpoints (`routes_aiuibuilder.py`)

**Unpublish** (mirrors the publish extraction):
- Extract `_unpublish_slug(s, slug, email, *, is_admin)` from
  `routes_projects.unpublish_app` (validate → `_user_can_see_project` →
  `_require_role("owner")` → delete `PublishedApp` row → idempotent). The admin
  `DELETE` route delegates to it.
- New `DELETE /api/aiuibuilder/{slug}/publish` (`current_user`) →
  `_unpublish_slug(s, slug, user.email, is_admin=False)` → 204.

**Enhance:**
- Add a shared core `_spawn_enhance(s, slug, email, prompt, *, is_admin) -> dict`
  that encapsulates: find the latest BUILD `TaskItem` for `slug` (the source;
  404 if none) → `_require_role(slug, email, "editor", is_admin=...)` → advisory
  lock `build:<slug>` → reject if a task for that slug is
  `running|planning|awaiting_input` (409) → create the enhancement `TaskItem`
  (`description="Enhance apps/<slug>/: <prompt>"`, `plan_status="approved"`,
  `built_app_slug=slug`) + `TaskExecution` → build the enhance prompt →
  `_run_execution` → return `{task_id, slug, status:"running"}`. (Extracted from
  the admin `enhance` route's core so the two don't duplicate; the admin route
  keeps its file/selection handling and calls the shared core for the spawn.)
- New `POST /api/aiuibuilder/{slug}/enhance` (`current_user`, body
  `{prompt}` 1–2000 chars) → `_spawn_enhance(s, slug, user.email,
  prompt, is_admin=False)`.

### 2. `webhook-handler/clients/tasks.py` + `clients/discord.py`
- `unpublish_app(email, slug)` → `DELETE /api/aiuibuilder/{slug}/publish` (204 → returns True).
- `enhance_app(email, slug, prompt)` → `POST /api/aiuibuilder/{slug}/enhance` → `{task_id, slug, status}`.
- `DiscordClient.edit_original` gains an optional `components` arg (mirrors the
  `post_channel_message` change) so the publish button's edited reply ("🎉
  Published! …") can carry the **Enhance + Unpublish** buttons. Backward
  compatible (None default).

### 3. `webhook-handler/handlers/app_builder_panel.py` (pure)
- New prefixes: `ENHANCE_PREFIX = "aiuibuild:enhance:"`,
  `UNPUBLISH_PREFIX = "aiuibuild:unpublish:"`,
  `ENHANCE_MODAL_PREFIX = "aiuibuild:enhancemodal:"`.
- `build_ready_components(slug, preview_url)` — **add an ✏️ Enhance button**
  alongside Publish + Open-preview.
- `build_published_components(slug, public_url)` — buttons for the "Published!"
  message: **✏️ Enhance + 🔌 Unpublish** + 🔗 Open live (link).
- `build_enhance_modal(slug)` — type-9 modal, paragraph input
  ("What do you want to change?", `custom_id="change"`), modal custom_id
  `aiuibuild:enhancemodal:<slug>`.
- Parsers/predicates: `is_enhance_button`, `slug_from_enhance_button`,
  `is_unpublish_button`, `slug_from_unpublish_button`, `is_enhance_modal`,
  `slug_from_enhance_modal` — all reject empty slug (raise `ValueError`).

### 4. `webhook-handler/handlers/commands.py`
- `run_panel_enhance(ctx, slug, prompt)`: resolve email (unlinked → friendly) →
  validate prompt non-empty → `tasks_client.enhance_app` → respond "Updating
  `slug` … I'll post the new preview here when it's ready" → start the **same
  `_watch_build`** watcher on the returned `task_id`.
- `run_panel_unpublish(ctx, slug)`: resolve email → `tasks_client.unpublish_app`
  → respond "`slug` is offline now (unpublished)."
- `_format_enhance_error` / reuse error mapping: 403 → owner/editor only; 404 →
  not found/not yours; 409 → "an update is already running — try again in a
  minute"; 400/422 → "couldn't start the update — check your description"; 0 →
  unreachable.
- `_format_unpublish_error`: 403 → owner only; 404 → "it's not live right now";
  0 → unreachable.

### 5. `webhook-handler/handlers/discord_commands.py`
- `_handle_message_component`: add branches — `is_enhance_button` → return an
  enhance **modal** (type 9); `is_unpublish_button` →
  `_handle_unpublish_component` (defer + `run_panel_unpublish`); (publish branch
  unchanged). Malformed ids → no-op (type 6).
- `_handle_modal_submit`: add branch — `is_enhance_modal(custom_id)` → extract
  the "change" text → defer + `run_panel_enhance(ctx, slug, change)`. (Existing
  `aiuibuild:build:` template-modal branch unchanged.)
- The published-message buttons are emitted via the build watcher's rich
  notifier path only for the publish *result* — so after a successful publish,
  `run_panel_publish` posts the "Published!" message with
  `build_published_components(slug, public_url)`.

## Data flow

```
[Enhance]
ready/published msg has [✏️ Enhance] (custom_id aiuibuild:enhance:<slug>)
 → click → modal "What do you want to change?"
 → submit (aiuibuild:enhancemodal:<slug>) → defer
 → run_panel_enhance → enhance_app → POST /api/aiuibuilder/<slug>/enhance
 → _spawn_enhance (edit task on same slug) → _watch_build polls → posts updated
   preview with [Publish][Enhance] buttons again

[Unpublish]
"Published!" msg has [🔌 Unpublish] (aiuibuild:unpublish:<slug>)
 → click → defer → run_panel_unpublish → unpublish_app
 → DELETE /api/aiuibuilder/<slug>/publish → "`slug` is offline now."
```

## Testing

- **webhook-handler (local, TDD):** pure builders (enhance/published components,
  enhance modal, parsers); `TasksClient.unpublish_app`/`enhance_app` (respx,
  asserting only `X-User-Email` sent); `run_panel_enhance`/`run_panel_unpublish`
  (linked/unlinked, success, 403/404/409 error copy, enhance starts the watcher);
  button + enhance-modal dispatch. All green locally.
- **tasks (Postgres env / post-deploy):** DB test for unpublish (owner unpublishes
  → 204 + row gone; non-owner 403; idempotent). Enhance is integration-heavy and
  spawns the agent — verified by the **live enhance click after deploy** (its DB
  test would need a real source task + agent run; treat the live click as
  authoritative, like publish).

## Deployment (two services, per `CLAUDE.md`)
1. **tasks:** `scp` changed files (`routes_projects.py`, `routes_aiuibuilder.py`)
   → `docker compose ... up -d --build tasks`. NEVER deploy local `templates.py`.
2. **webhook-handler:** `scp` changed files (`clients/tasks.py`,
   `handlers/app_builder_panel.py`, `handlers/commands.py`,
   `handlers/discord_commands.py`) → rebuild.
Verify `/tasks/healthz`, bot `Up`, then a live **Enhance** + **Unpublish** click.
