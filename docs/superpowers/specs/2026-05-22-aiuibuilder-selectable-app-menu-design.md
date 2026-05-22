# Selectable "Your apps" List → Per-Project Menu (Discord App Builder)

**Date:** 2026-05-22
**Status:** Approved design — ready for implementation planning
**Area:** Discord App Builder (`webhook-handler`)

## Problem

The Discord App Builder lets users build, publish, and enhance apps from the
`#app-builder` channel. The `/aiui aiuibuilder list` command returns a **plain
text** list of the user's apps (slug, name, role, publish status) with **no
interactivity**. To act on an app, the user must remember its slug and type a
separate command (`status <slug>`, `open <slug>`) or scroll back to the app's
original build message to find its Publish/Enhance/Unpublish buttons.

We want the list itself to be actionable: pick an app and immediately get a menu
of actions for that app.

## Current behavior (grounded in code)

All paths below are on the **production VPS** (`/root/proxy-server`), currently
**uncommitted** — these files do not yet exist in git or in the local checkout.

- **`webhook-handler/handlers/commands.py`** — `_handle_aiuibuilder` (~line 1343)
  handles the `list | status | open | build | templates` actions. The `list`
  branch (~line 1429) calls `self._tasks_client.list_projects(email)` and renders
  text lines: `` `{slug}` — {name} [{role}] {public_url or "(not published)"} ``,
  then `await ctx.respond(reply)`. `ctx.respond` carries **content only**.
  Existing per-app run methods: `run_panel_build`, `run_panel_publish`,
  `run_panel_enhance`, `run_panel_unpublish`. Mutations check owner/editor
  server-side (the "Only the app's owner or an editor can change it." guard
  ~line 1602).
- **`webhook-handler/handlers/app_builder_panel.py`** — pure component builders,
  **no I/O**, unit-tested in `tests/test_app_builder_panel.py`. Defines the
  `custom_id` prefixes (`aiuibuild:publish:<slug>`, `:enhance:<slug>`,
  `:unpublish:<slug>`, `:enhancemodal:<slug>`, template `:tpl:`/`:build:`) and
  builders `build_ready_components` (Publish + Enhance + optional Open-preview
  link) and `build_published_components` (Enhance + Unpublish + optional Open-live
  link), plus `is_*_button` / `slug_from_*_button` helpers.
- **`webhook-handler/handlers/discord_commands.py`** — `_handle_message_component`
  routes button clicks (`MESSAGE_COMPONENT`, type 3) by `custom_id` prefix:
  Enhance → opens a modal; Publish/Unpublish → ephemeral/deferred ACK +
  `asyncio.create_task(run_panel_*)`; unknown id → harmless no-op
  (`DEFERRED_UPDATE_MESSAGE`, type 6, never a 500). It does **not** yet handle
  string-select submits (`data.component_type == 3` with `data.values`).
- **`webhook-handler/clients/tasks.py`** — `TasksClient` exposes
  `list_projects`, `get_project_status` (returns `name, slug, role, published,
  public_url, last_commit_at`), `publish_app`, `unpublish_app`, `enhance_app`.
- **`scripts/register_discord_commands.py`** — registers the `/aiui` subcommand
  tree; `aiuibuilder` arg help is `list | status <slug> | open <slug>`.

## Goal

Make `/aiui aiuibuilder list` selectable. Selecting an app posts an **ephemeral**
(only-the-picker-sees-it) menu of **state-aware** action buttons for that app.

### Locked design decisions
1. **Selection mechanism:** a Discord **string select menu** (dropdown), appended
   below the existing text list. (Chosen over a button grid: native, compact, one
   component regardless of app count, status visible inline, smallest handler change.)
2. **Menu visibility:** **ephemeral** — only the user who selected sees it; the
   channel stays clean; repeated picks replace their own ephemeral menu.
3. **Menu contents:** **state-aware buttons + a Status button.**
   - Not published: `✏️ Enhance` · `🟢 Publish` · `🔗 Open preview` · `ℹ️ Status`
   - Published: `✏️ Enhance` · `🔌 Unpublish` · `🔗 Open live` · `ℹ️ Status`
   - "Enhance" is the existing AI-edit path (opens a "What do you want to change?"
     modal). A single Discord action row holds ≤5 buttons; 4 fits.

## Design

### Component / file changes (3 files)

**1. `app_builder_panel.py` (pure builders + id helpers — no I/O):**
- New id constants: `APP_SELECT_ID = "aiuibuild:appselect"` (the dropdown's
  `custom_id`), `STATUS_PREFIX = "aiuibuild:status:"`.
- `build_apps_select_components(projects: list[dict]) -> list[dict]`: one action
  row containing a string select (component type 3). One option per project:
  `{"label": name[:100], "value": slug[:100], "description":
  ("published" if public_url else "not published")[:100]}`. Cap at **25** options
  (Discord max). `placeholder="Select an app to manage…"`, `min_values=1`,
  `max_values=1`. Caller must not invoke this with an empty list (Discord rejects
  a 0-option select).
- `build_project_menu_components(slug, *, published, public_url, preview_url)
  -> list[dict]`: the state-aware row described above, including the new Status
  button (`STATUS_PREFIX + slug`). Link buttons (Open preview / Open live) are
  included only when their URL is non-empty.
- Helpers: `is_app_select(custom_id)`, `is_status_button(custom_id)`,
  `slug_from_status_button(custom_id)` (reusing the existing `_slug_after` guard).

**2. `discord_commands.py` (`_handle_message_component`):**
- **Dropdown branch:** if `data.get("component_type") == 3` and
  `is_app_select(custom_id)`, read `slug = (data.get("values") or [None])[0]`.
  Guard a missing/empty slug as a no-op. Build a `CommandContext` (mirroring the
  Publish-button handler) wired with `respond_components` (see below), return an
  **ephemeral deferred** ACK `{"type": 5, "data": {"flags": 64}}`, and
  `asyncio.create_task(self.router.run_panel_menu(ctx, slug))`.
- **Status-button branch:** if `is_status_button(custom_id)`, same ephemeral
  deferred + `asyncio.create_task(self.router.run_panel_status(ctx, slug))`.
- Ordering: place these checks alongside the existing `is_publish_button` /
  `is_unpublish_button` / `is_enhance_button` checks before the
  `is_panel_button` fallthrough so unrelated components stay a no-op.

**3. `commands.py`:**
- Add **one** optional callback to `CommandContext`:
  `respond_components: Callable[[str, list[dict]], Awaitable[None]] | None = None`.
  The existing `respond(str)` signature is unchanged. In
  `discord_commands._handle_application_command` and the new dropdown/status
  branches, set `respond_components` to a closure calling
  `self.discord.edit_original(interaction_token=…, content=…, components=…)`.
- `_handle_aiuibuilder` `list` branch: after building the text reply, if
  `projects` is non-empty and `ctx.respond_components` is set, call
  `await ctx.respond_components(reply, build_apps_select_components(projects))`;
  otherwise fall back to `await ctx.respond(reply)` (keeps the non-Discord/text
  path working).
- New `run_panel_menu(ctx, slug)`: `get_project_status(email, slug)`, then
  `await ctx.respond_components(header, build_project_menu_components(...))` where
  `header = f"**{name}** (`{slug}`) — {'published' if published else 'not published'}"`.
  Resolve the user email from `self._discord_user_email_map[ctx.user_id]` exactly
  as `_handle_aiuibuilder` does; unlinked user → friendly message.
- New `run_panel_status(ctx, slug)`: `get_project_status`, format the same text
  block the existing `status` action produces (name, role, published, URL, last
  commit), `await ctx.respond(...)`.
- Both new methods catch `TasksAPIError` and reuse the existing friendly messages
  (404 → "Project not found or not yours.", status 0 → "Tasks service
  unreachable, try again.", else → generic).

### Data flow
1. `/aiui aiuibuilder list` → deferred → `_handle_aiuibuilder` → `list_projects` →
   text + dropdown via `respond_components`.
2. User picks an app → `MESSAGE_COMPONENT` (component_type 3, custom_id
   `aiuibuild:appselect`, `values=[slug]`) → ephemeral deferred ACK + background
   `run_panel_menu`.
3. `run_panel_menu` → `get_project_status(email, slug)` (fresh state, not the
   possibly-stale list row) → edits the ephemeral with the state-aware menu.
4. User clicks a menu button → Publish/Enhance/Unpublish reuse the **existing**
   handlers unchanged; the new Status button → `run_panel_status`.

### Preview-URL sourcing (implementation detail to confirm)
`get_project_status` returns `public_url` but not a preview URL. The "Open
preview" link for not-yet-published apps follows the pattern
`{PUBLIC_BASE}/tasks/preview-app/{slug}/`. Source `PUBLIC_BASE` from existing
config/env in `commands.py` (do not hardcode the domain). If no preview base is
configured, omit the Open-preview link rather than emit a broken URL.

## Security / permissions
No new attack surface. The dropdown is built from `list_projects(email)`, which
is per-user, so a user can only ever select their own apps. `get_project_status`
returns 404 for anything not theirs. Every mutation (publish/unpublish/enhance)
already re-verifies owner/editor server-side. The select `value` is a slug the
server already authorized for this user; it is never used to construct a
filesystem path or shell command client-side.

## Error handling
- **Empty project list:** do not attach a dropdown (Discord rejects a 0-option
  select); keep the existing "no projects yet." text.
- **> 25 apps:** cap the dropdown at 25 options; the text list still shows all.
  Real pagination is out of scope.
- **`TasksAPIError`:** reuse existing friendly 404 / unreachable / generic copy.
- **Malformed or unknown component id / missing `values`:** no-op
  (`DEFERRED_UPDATE_MESSAGE`), never a 500 — matches the current handler.
- **Discord 3s window:** every tasks-service call happens in the background task
  after the immediate deferred ACK.

## Testing
- **Pure builder unit tests** (`tests/test_app_builder_panel.py`):
  `build_apps_select_components` option shape and `value == slug`, the 25-option
  cap, `description` reflects publish state; `build_project_menu_components`
  emits the correct button set for published vs not-published and includes link
  buttons only when the URL is present and the Status button always; id helpers
  `is_app_select` / `is_status_button` / `slug_from_status_button` round-trip and
  reject foreign ids.
- **Handler tests** (`discord_commands`): a string-select interaction returns an
  ephemeral deferred and schedules `run_panel_menu` with the selected slug; the
  Status button schedules `run_panel_status`; an unknown select custom_id and a
  select with empty `values` are no-ops.
- **Router tests** (`commands`) with a fake `TasksClient`: `run_panel_menu` and
  `run_panel_status` for 404, published, and not-published; unlinked Discord user
  → friendly message; empty `list_projects` → no dropdown.

## Out of scope (YAGNI)
Pagination beyond 25 apps, rename/delete actions, multi-select, and
auto-refreshing the dropdown after a publish/unpublish state change.

## Implementation logistics (decided at planning, not here)
This entire feature lives in **uncommitted VPS files**. Before implementing we
must choose where the work happens — pull the App Builder files into the local
checkout, build + test locally, then deploy back; or edit on the VPS — and how
the result (plus the surrounding uncommitted VPS work) gets committed to git.
