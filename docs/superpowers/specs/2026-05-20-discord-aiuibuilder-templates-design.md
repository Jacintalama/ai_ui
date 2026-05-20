# Discord App Builder — template selection (`/aiui aiuibuilder build <template> …`) — Design

**Date:** 2026-05-20
**Author:** Claude (paired with Jacinta)
**Status:** Draft for review
**Branch:** `feat/vm-agent-flight-mcp`
**Builds on:** `2026-05-20-discord-aiuibuilder-build-design.md` (the one-shot Discord build, already shipped)

## Goal

The shipped Discord build (`/aiui aiuibuilder build "<description>"`) is **template-less** —
it produces a from-scratch frontend-only app. The web App Builder, by contrast, offers a
gallery of ~18 templates (landing, portfolio, crud, dashboard, …) that inject curated rules
and, for many, copy in a polished prebuilt base app. This spec lets a Discord user **pick one
of those same templates** so a Discord build starts from the same high-quality baseline the
web users get.

After this change:

```
/aiui aiuibuilder templates                                  → lists the templates
/aiui aiuibuilder build portfolio a UX designer named Maya   → builds from the portfolio template
/aiui aiuibuilder build a kanban board for my team           → first word not a template → template-less (unchanged)
```

## Non-Goals

- **Connecting Supabase from Discord.** The web shows a "connect Supabase" popup for
  database-backed templates; Discord can't. All Discord template builds force
  `storage="none"`, so the Supabase gate is never reached. Database templates run in their
  built-in localStorage fallback mode. Connecting real persistence stays a web-App-Builder
  action.
- **The `auth` template as a working app.** `auth` is the one template with no localStorage
  fallback (it shows a "connect Supabase" full-page message without a DB). It's still
  *buildable* from Discord (produces the login UI shell, same as the web's no-Supabase
  behavior) but is **flagged** in the `templates` listing as needing the web App Builder.
- **The "instant build" shortcut.** The web copies a base app as-is (skipping the agent) when
  the description is generic. Discord always runs the agent to personalize — the user typed a
  description, so personalize it. Simpler, one code path.
- **A typed Discord option per field / template dropdown.** The `aiuibuilder` subcommand keeps
  its single free-text `args` string; the template is the first word of the build args. No
  command-tree re-registration.
- **Template preview images / SVG mockups in Discord.** The `templates` listing is text only.
- **Changing the web `/api/templates` endpoint or the `TEMPLATES` registry.** This is additive.

## Background: how the web template build works (verified)

`templates.py` is the single source of truth: a `TEMPLATES: list[Template]` registry. Each
`Template` has `key, label, emoji, description, placeholder, rules, storage ("none"|"supabase"),
role_tag, feature_bullets, svg_mockup`. Helpers:

- `is_valid_key(key) -> bool`
- `storage_for(key) -> str`
- `requires_supabase(key, user_storage_choice) -> bool` — **True only when the template's
  storage is "supabase" AND the user *chose* "supabase".** Choosing "none" ⇒ no gate.
- `build_rules_for(key, storage) -> str` — `_BASE_RULES` + (`_CUSTOMIZE_DIRECTIVE` if a
  prebuilt base app exists for the key, else `_GENERATION_LAYOUT`) + the template's `rules` +
  the storage instruction. Returns `""` for unknown keys.
- `_has_template_app(key) -> bool` — True iff `template_apps/<key>/index.html` exists.

`routes_tasks.create_task` (admin) for a template build:
`description = f'PROJECT NAME: "{slug}". … {build_rules_for(key, storage)}\n\nUSER REQUEST:\n{description}'`,
then copies the base app (`_copy_template_app(key, slug, app_name=_humanize_slug(slug))`) when
one exists, else `_ensure_app_skeleton(slug, storage)`. The build then runs `build_prompt`
over that composed description.

`GET /api/templates` (`routes_templates.py`) returns the catalog but is **`current_admin`**-gated
and omits `rules`.

The Discord bot sends **X-User-Email only** (never admin / cron secret), so it cannot use the
admin catalog endpoint and cannot create admin tasks. The shipped Discord build added a
**user-scoped** `POST /api/aiuibuilder/build` + `GET /api/aiuibuilder/build/{task_id}` that reuse
`_run_execution`. This spec extends that user-scoped surface.

## Architecture

```
Discord user        webhook-handler bot                       tasks service
   |                       |                                        |
   | build portfolio <txt> |                                        |
   |---------------------->| GET /api/aiuibuilder/templates ------->|  current_user
   |                       |   (learn valid keys; resilient: on     |  -> catalog (key,label,
   |                       |    failure fall back to template-less) |      emoji,description,
   |                       |<---------------------------------------|      has_app,note)
   |                       | first word "portfolio" is a key →      |
   |                       |   template_key="portfolio"             |
   |                       |   description="<txt>"                  |
   |                       | POST /api/aiuibuilder/build ---------->|  current_user
   |                       |   {description, template_key}          |  validate key (422 if bad)
   |                       |   X-User-Email only                    |  storage forced "none"
   |                       |                                        |  copy base app or scaffold
   |                       |                                        |  desc = slug-dir + rules +
   |                       |   201 {task_id, slug, status}          |        USER REQUEST + txt
   |                       |<---------------------------------------|  spawn _run_execution
   |  "Building <slug> …"  |                                        |
   |<----------------------| (watcher polls build status, posts the preview link — unchanged)
```

## Components

### 1. tasks service — `GET /api/aiuibuilder/templates` (new, in `routes_aiuibuilder.py`)

`current_user` (X-User-Email). Reads the in-process `TEMPLATES` registry — no DB. Returns
`list[TemplateBrief]`:

```
TemplateBrief { key: str, label: str, emoji: str, description: str,
                has_app: bool, note: str }
```

- `has_app = _has_template_app(t.key)`.
- `note` is derived server-side (one place, near the registry knowledge):
  - `t.key == "auth"` → `"needs Supabase — use the web App Builder"`
  - else `t.storage == "supabase"` → `"saves in your browser"`
  - else → `""` (frontend-only)
- `rules` is intentionally NOT returned (same prompt-injection guard as `/api/templates`).
- **Excludes `blank` and `custom`.** Both are equivalent to the default template-less Discord
  build (`build <description>` with no key): `custom` has empty rules, and `blank`'s rules tell
  the agent to ask 3-5 clarifying questions — which can't be answered over Discord (it would
  surface as `needs_input`). Filtering them keeps the listing focused on the real
  base-app/curated templates AND means the bot (which derives valid keys from this catalog)
  treats `build blank …` / `build custom …` as ordinary template-less builds. Returns the rest
  of the registry in its existing order.

### 2. tasks service — `POST /api/aiuibuilder/build` gains `template_key`

`BuildRequest` gains `template_key: str | None = Field(default=None, max_length=64)`. Leave
the inbound `description` field's `max_length` (4000) as-is — the 20 000-char cap below applies
to the *server-composed* description (slug directive + rules + user text), not the user's
inbound free text, so the rules text (a few KB) never crowds out the user's request.

`_create_and_spawn_build(email, seed, description, template_key=None)`:
- If `template_key` is not None: `if not is_valid_key(template_key): raise HTTPException(422,
  "Unknown template")`.
- Storage is **always `"none"`** for this path (never gate on Supabase).
- Slug allocation, concurrency guard, task/execution rows: unchanged from the shipped build.
- **Description composition** via a new pure helper `_compose_build_description(slug,
  template_key, description)`:
  - Always begins with the existing slug directive (from `_bind_slug_description`'s text).
  - If `template_key`: insert `build_rules_for(template_key, "none")` between the slug
    directive and a `USER REQUEST:` line, then the user's description.
  - If no `template_key`: identical to today (slug directive + `USER REQUEST:`-less form is
    fine; keep the current `_bind_slug_description` output to avoid changing template-less
    behavior).
  - Capped at 20 000 chars (same as today / the web).
- **Scaffolding** (best-effort, swallow errors), via deferred imports from `routes_tasks`:
  - If `template_key and _has_template_app(template_key)`:
    `_copy_template_app(template_key, slug, app_name=_humanize_slug(slug))`.
  - Else: `_ensure_app_skeleton(slug, None)` (today's behavior).
- The prompt is `build_prompt(description=<composed>, …, slug=slug, …)` — unchanged call,
  composed description carries the rules (mirrors the web).
- Returns `(task_id, slug)` as today.

`start_build` route passes `body.template_key` through.

### 3. webhook-handler — `clients/tasks.py`

- `list_templates(user_email) -> list[dict]` → `GET /api/aiuibuilder/templates` (X-User-Email
  only, via the existing `_request`).
- `start_build(user_email, description, name=None, template_key=None)` → include
  `template_key` in the JSON body (kept alongside the existing `description`/`name`).

### 4. webhook-handler — `handlers/commands.py` `_handle_aiuibuilder`

- New **`templates`** action: `templates = await self._tasks_client.list_templates(email)`;
  reply with one line per template: `` `key` — label — note `` (truncate at the 2000-char
  Discord limit with `… +N more`). On `TasksAPIError`, reply with the build-flavored error.
- **`build`** action gains template resolution:
  - Resolve the template **from the raw remainder before the existing quote-strip**: split the
    remainder once on whitespace into `first, rest`. (The current branch does
    `description = remainder.strip().strip('"').strip()`; the split for template detection must
    run on the un-quote-stripped remainder so `build portfolio "a UX designer"` yields
    `first="portfolio"`, not a leading quote. Quote-strip is then applied to the chosen
    description text.)
  - Fetch valid keys: `try: keys = {t["key"] for t in await self._tasks_client.list_templates(email)} except TasksAPIError: keys = set()` (resilient — a catalog failure degrades to template-less, never blocks a build).
  - If `first.lower() in keys`: `template_key = first.lower()`, `description = rest`.
    Else: `template_key = None`, `description = <full args>`.
  - If `template_key` and `description` is empty: synthesize `description = f"a {label}"`
    using the label from the fetched catalog (so `build portfolio` alone still works).
  - Call `start_build(email, description, template_key=template_key)`; ack and spawn the
    watcher exactly as today.
- Usage/help text updated to mention `templates` and `build [template] <description>`.

## Security

- **X-User-Email only, end to end** — unchanged. `list_templates` and the extended
  `start_build` go through `TasksClient._request`, which sends only X-User-Email.
- **New catalog endpoint is `current_user`** (not admin) and returns no secrets and no `rules`.
- **`template_key` is validated** server-side against `is_valid_key`; an invalid key is a 422,
  never reaches the filesystem. The key only ever indexes the in-repo registry / the
  `template_apps/<key>/` directory (path components are fixed registry keys, not user paths).
- Forced `storage="none"` means the Supabase gate / awaiting_supabase state is unreachable
  from Discord — no stuck-build lockout from this path.

## Error handling

- Invalid `template_key` → 422 → the bot's build-error mapping says "check your input"
  (already handles 422). 
- Catalog fetch failure in the `build` path → the bot falls back to a template-less build (the
  user still gets an app). In the `templates` path → a friendly "couldn't load templates" reply.
- All tasks↔bot calls go through `_request` (raises `TasksAPIError(status=0, …)` on network
  failure). Scaffolding / `_copy_template_app` failures are swallowed (the agent recreates the
  dir), same as the shipped build.

## Testing (TDD, all green)

**tasks service (`tests/test_routes_aiuibuilder.py`):**
- `_compose_build_description`: template-less form unchanged; with a key, contains the slug
  directive, the template's rules markers (e.g. the template's PURPOSE text via
  `build_rules_for`), and the user request, in that order; capped at 20 000.
- `GET /api/aiuibuilder/templates`: 200 returns the catalog (count == len(TEMPLATES), each item
  has key/label/note, no `rules` field); `auth` note mentions Supabase; a db-backed template
  note says "saves in your browser"; 401 without X-User-Email.
- `POST /build` with a valid `template_key` (executor mocked) → 201, task created; with an
  invalid `template_key` → 422; without `template_key` → behaves as today.

**webhook-handler (`tests/`):**
- `TasksClient.list_templates` (respx): GET path, X-User-Email present, no cron secret.
- `TasksClient.start_build` includes `template_key` in the body (None when omitted).
- `_handle_aiuibuilder` `templates` action: lists; on error replies gracefully.
- `_handle_aiuibuilder` `build`: known first word → `start_build` called with that
  `template_key`; unknown first word → `template_key=None` and full text as description;
  `list_templates` raising → still builds template-less; `build <key>` with no description →
  synthesized description.

**Live e2e after deploy:** build from a real template (e.g. `portfolio`) through the deployed
API exactly as the bot does (X-User-Email only), confirm it completes, the app is built at the
allocated slug, and the preview serves; clean up.

## Deployment

Workflow A: `scp` the three changed source files — `mcp-servers/tasks/routes_aiuibuilder.py`,
`webhook-handler/clients/tasks.py`, `webhook-handler/handlers/commands.py` — to
`/root/proxy-server/`, then `docker compose -f docker-compose.unified.yml up -d --build tasks
webhook-handler`, then `/healthz` + live smoke. No new tasks-service file (the catalog route
lives in the existing `routes_aiuibuilder.py`). No new env vars, no command re-registration.
