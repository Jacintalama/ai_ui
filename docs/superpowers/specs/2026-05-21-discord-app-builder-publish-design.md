# Discord App Builder — Publish — Design

**Date:** 2026-05-21
**Status:** Approved (pending spec review)
**Topic:** Let a Discord user publish an app they built, straight from the
`#app-builder` channel — via a **Publish** button on the build-ready message —
so they never have to open the web App Builder to go live.

## Problem

From Discord today you can build, list, check status, and `open` an app — but
**not publish it**. `open` even tells you to "publish it from the App Builder UI
first." The publish API exists, but it is **admin-only** (`current_admin`), and
the Discord bot authenticates as a plain user (`X-User-Email` only, never the
admin/cron header — a deliberate security choice in `TasksClient`). So Discord
can't reach it.

## Goal

- A **Publish** button on the bot's "build ready" message. The owner clicks it →
  the app goes live at `https://<slug>.ai-ui.coolestdomain.win/` → the bot posts
  the live URL.
- Reuse the existing publish logic and the existing button/modal interaction
  plumbing. No new infrastructure.

## Non-goals (keep it simple)

Iterative "build chat", members/sharing, custom domains, versions/rollback,
**unpublish**. (Unpublish is a plausible tiny follow-up later — explicitly not
now.)

## Key facts (verified)

- `routes_projects.publish_app` (admin-only) does: `_validate_slug` →
  `_user_can_see_project` → `_require_role(slug, email, "owner", is_admin=...)` →
  verify `apps/<slug>/index.html` exists → idempotent insert of a `PublishedApp`
  row (`slug`, `published_by`, `public_host`). Live URL = `_public_url_for(slug)`
  = `https://<slug>.<PUBLIC_DOMAIN>/`.
- `_require_role` treats the **original build assignee as an implicit owner**
  even without a `ProjectMember` row, AND a completed build also auto-inserts a
  `project_members` owner row. So the Discord builder is the owner either way.
- The Discord `aiuibuilder` build watcher (`CommandRouter._watch_build`) already
  posts a "ready" message to the channel via `ctx.notify_channel` (bot token,
  outlives the interaction). Today it is plain text.
- Buttons ride the existing `/webhook/discord` interactions endpoint (same
  Ed25519 signature, same `_handle_message_component` dispatch added previously).

## Components

### 1. Tasks service — user-scoped publish endpoint

- **Extract** the publish core from `routes_projects.publish_app` into a shared
  helper, e.g. `async def _publish_slug(s, slug, email, *, is_admin) -> dict`
  returning `{published, public_url, published_at, published_by}`. It performs
  the `_user_can_see_project` + `_require_role("owner")` + index.html check +
  idempotent `PublishedApp` insert. The existing admin `publish_app` route calls
  it with `is_admin=user.is_admin` (behavior unchanged).
- **New** `POST /api/aiuibuilder/{slug}/publish` in `routes_aiuibuilder.py`
  (auth = `current_user`). Calls `_publish_slug(s, slug, user.email,
  is_admin=False)` — so only a project **owner** (the builder) can publish.
  Imports the helpers from `routes_projects` (no circular import: routes_projects
  does not import routes_aiuibuilder). Validates the slug with the existing
  `_SLUG_RE`/`_validate_slug`. Returns the publish status (200).

### 2. `webhook-handler` — `TasksClient.publish_app`

```python
async def publish_app(self, user_email: str, slug: str) -> dict:
    resp = await self._request("POST", f"/api/aiuibuilder/{slug}/publish", user_email)
    return resp.json()
```
Errors surface as `TasksAPIError` (existing pattern): 403 (not owner), 404 (not
yours), 400 (no index.html), 0 (unreachable).

### 3. `webhook-handler/handlers/app_builder_panel.py` — pure ready-message buttons

- `PUBLISH_PREFIX = "aiuibuild:publish:"`
- `build_ready_components(slug, preview_url) -> list[dict]`: one action row with
  a green **Publish** button (`custom_id=aiuibuild:publish:<slug>`) and, when
  `preview_url` is set, a **🔗 Open preview** link button (style 5, no handler
  needed). Slugs are `[a-z0-9-]` ≤ ~44 chars, so the custom_id stays < 100.
- `is_publish_button(custom_id)` / `slug_from_publish_button(custom_id)` helpers.

### 4. Build-ready message carries the buttons (Discord only)

`CommandRouter._watch_build`, on `status == "completed"`, posts the ready message
with the Publish/Open buttons **when the channel notifier supports components**.
Implementation keeps the watcher platform-agnostic: `CommandContext` gets an
optional `notify_channel_rich: Callable[[str, list[dict]], Awaitable[None]] |
None`. The Discord modal/build path sets it to a closure that calls
`discord.post_channel_message(channel_id, msg, components=...)`. If it's None
(Slack/voice), the watcher falls back to the existing plain
`ctx.notify_channel(msg)`. `DiscordClient.post_channel_message` gains an optional
`components` arg (defaults to none → unchanged behavior).

### 5. Publish button dispatch + router method

- `discord_commands._handle_message_component`: if `is_publish_button(custom_id)`,
  parse the slug, build a `CommandContext` (respond via `edit_original`, plus a
  channel notifier), fire-and-forget `router.run_panel_publish(ctx, slug)`, and
  return a deferred ACK (`DEFERRED_CHANNEL_MESSAGE`). Mirrors the modal-submit
  handler. (Existing `aiuibuild:tpl:` template buttons keep working — the publish
  branch is checked alongside them.)
- **New** `CommandRouter.run_panel_publish(ctx, slug)`: resolve email from the
  Discord→email map (unlinked → "isn't linked"); call
  `tasks_client.publish_app(email, slug)`; on success respond
  `"🎉 Published! Live at <public_url>"`; map `TasksAPIError` to friendly copy
  (403 → "only the app's owner can publish it"; 400 → "this app isn't publishable
  yet (no index.html)"; 0 → "tasks service unreachable, try again"; already
  published returns published=true → "already live at <url>").

### 6. Copy updates

- `_handle_aiuibuilder` `open`: drop "publish it from the App Builder UI first";
  if not published, say "not published yet — click **Publish** on its build
  message, or build it again."
- `help`: show the lifecycle — build → (preview) → **publish** → open/share.

## Data flow

```
build completes
  → _watch_build posts: "`slug` is ready (preview): <preview_url>"
     + [🟢 Publish (aiuibuild:publish:slug)] [🔗 Open preview (link)]
owner clicks Publish
  → POST /webhook/discord {type:3, custom_id:"aiuibuild:publish:slug"}
  → _handle_message_component → defer (type 5) + create_task(run_panel_publish)
  → run_panel_publish → TasksClient.publish_app(email, slug)
       → POST /api/aiuibuilder/slug/publish (current_user)
       → _publish_slug(owner check + index.html + PublishedApp insert)
  → bot edits: "🎉 Published! Live at https://slug.ai-ui.coolestdomain.win/"
```

## Testing (TDD)

- **tasks** (`tests/test_routes_aiuibuilder_publish.py`): owner publishes →
  200 + public_url; non-member → 404/403; missing `index.html` → 400; re-publish
  idempotent → 200 same url. (Reuse the existing tasks test fixtures.)
- **webhook-handler:**
  - `build_ready_components` / publish-button parsers (pure) in
    `tests/test_app_builder_panel.py`.
  - `TasksClient.publish_app` (respx) in `tests/test_tasks_client.py`.
  - `run_panel_publish` (`tests/test_panel_build.py` or a new file): unlinked,
    success, 403 non-owner, 400 no-index, already-published.
  - publish-button dispatch in `tests/test_app_builder_interactions.py`:
    `type:3 + aiuibuild:publish:<slug>` → deferred ACK + `run_panel_publish`
    called with the slug.
- Regression: existing template-button + modal-submit tests stay green.

## Deployment

Touches **both** services, so deploy is two-part (per `CLAUDE.md`):
1. `tasks` (backend) — via `ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh`
   (it watches `mcp-servers/`). NEVER deploy local `templates.py`.
2. `webhook-handler` (Discord bot) — manual `scp` of each changed file, then
   `docker compose ... up -d --build webhook-handler`.
Verify `/tasks/healthz` and that the bot is `Up`, then click Publish on a real
build to confirm end to end.
