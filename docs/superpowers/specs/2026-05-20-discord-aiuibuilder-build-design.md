# Discord `/aiui aiuibuilder build` — one-shot App Builder over Discord — Design

**Date:** 2026-05-20
**Author:** Claude (paired with Jacinta)
**Status:** Draft for review
**Branch:** `feat/vm-agent-flight-mcp`

## Goal

Lukas's vision: "connect it through Discord similar to App Builder but on Discord ...
so AIUI can become a bot." The existing `/aiui aiuibuilder` subcommand is **read-only**
(`list` / `status` / `open`). This spec adds the missing verb: **kick off an actual
App Builder build from Discord**, in one shot, and have the bot post the result back.

After this change a Discord user can type:

```
/aiui aiuibuilder build "a todo list with dark mode"
```

and the bot replies "Building `todo-list-a1b2` …", runs the same Claude agent pipeline
the web App Builder uses, and posts the preview link in the channel when it's done.

## Non-Goals

- **Multi-turn / conversational build (Plan mode).** The web App Builder asks 1–2
  clarifying questions before building (`/api/tasks/chat` → `BUILD_SUGGESTION:`). v1
  is strictly one-shot: the user's single description goes straight to a build. A
  stateful Discord-thread interview is explicitly out of scope.
- **Enhance / iterate from Discord** (`enhance <slug> "<change>"`). Read + build only.
  Iterating stays in the web UI for v1.
- **Template selection / Supabase-backed builds.** The web flow offers a template
  gallery and a Supabase connect gate. The Discord build is **template-less and
  frontend-only** (no `template_key`, no `storage`) — which sidesteps the Supabase
  gate entirely. Backed apps stay a web-UI action.
- **Publishing from Discord.** The bot returns the *draft preview* URL (publicly
  viewable, persists for static apps). Publishing to a permanent `<slug>.ai-ui…`
  subdomain stays an explicit web-UI / owner action.
- **Custom slug / rename from Discord.** The slug is auto-generated. Renaming is a
  web-UI action (`POST /api/projects/{slug}/rename`).
- **Concurrent builds.** Exactly one build runs platform-wide at a time (see Memory
  & Concurrency). No build queue in v1 — a busy build returns a "try again" message.
- **Persisting the watcher across bot restarts.** If the webhook-handler restarts
  mid-build the in-memory watcher is lost (the build itself keeps running on the
  tasks service). The user can still check `/aiui aiuibuilder status <slug>`.

## Background: how the web App Builder build works today

1. `POST /api/tasks` (`current_admin`) creates a `TaskItem` with `action_type="BUILD"`.
2. `POST /api/tasks/{id}/execute` (`current_admin`) spawns the Claude agent via
   `agent_executor.get_executor()` (local subprocess or remote VM), streams output,
   and runs `_run_execution(...)` which parses the COMPLETED/NEEDS_INPUT/FAILED
   sentinel and — on completion — auto-inserts the task's `assignee_email` as the
   project **owner** in `tasks.project_members`.
3. Read endpoints `GET /api/projects` and `GET /api/projects/{slug}/status` are
   **`current_user`** (X-User-Email), ownership-scoped — these are what Discord's
   read-only `list`/`status`/`open` already use.

**The gap:** every *build* endpoint is `current_admin`-gated. The Discord bot, by
deliberate security design (`webhook-handler/clients/tasks.py`), sends **`X-User-Email`
only** — never the operator/cron secret and never admin headers. So a Discord build
would `403`. We need a **user-scoped build entry point**.

## Approach

A new, isolated **user-scoped build module** in the tasks service that mirrors what
the web "create + execute" does, but with `current_user` auth and per-caller
ownership — reusing the proven `_run_execution` pipeline. The bot fires the build and
**watches it in the background**, keeping the tasks service Discord-agnostic.

Approaches considered and rejected:

- **Bot acts as admin / operator** (send admin or `X-Cron-Secret` headers to the
  existing endpoints). Rejected — breaks the established security model; every Discord
  user would gain admin reach over *all* projects.
- **Drive the web Plan-mode chat** (`/api/tasks/chat`). Rejected — admin-gated,
  multi-turn, designed for the browser chat UI. Overkill for one-shot.

## Architecture

```
Discord user      Discord            webhook-handler                 tasks service
   |                |                     |                               |
   | /aiui          |                     |                               |
   | aiuibuilder    |                     |                               |
   | build "<desc>" |                     |                               |
   |--------------->|  POST /webhook/     |                               |
   |                |  discord (signed)   |                               |
   |                |-------------------->| verify Ed25519                |
   |                |                     | parse → ("aiuibuilder",       |
   |                |                     |          "build \"<desc>\"")  |
   |                |  type=5 (DEFERRED)  |                               |
   |                |<--------------------|                               |
   |                |                     | _handle_aiuibuilder:          |
   |                |                     |   map discord_id → email      |
   |                |                     |   tasks_client.start_build()  |
   |                |                     |   X-User-Email ONLY            |
   |                |                     |------------------------------>| POST /api/aiuibuilder/build
   |                |                     |                               |   current_user
   |                |                     |                               |   make slug, create BUILD task
   |                |                     |                               |   scaffold apps/<slug>/
   |                |                     |                               |   asyncio _run_execution(...)
   |                |                     |   201 {task_id, slug,         |
   |                |                     |        status:"running"}      |
   |                |                     |<------------------------------|
   |                | PATCH @original     |                               |
   |                | "Building <slug>…"  |                               |
   |                |<--------------------|                               |
   |                |                     | spawn _watch_build():         |
   |                |                     |   loop: get_build_status()    |
   |                |                     |---- every ~12s -------------->| GET /api/aiuibuilder/build/{id}
   |                |                     |   {status, slug, preview_url} |   current_user, owner-checked
   |                |                     |<------------------------------|
   |                |                     |  (agent runs minutes on VM)   |
   |                | POST /channels/     | on terminal status:           |
   |                | {channel_id}/       |   notify_channel(...) via     |
   |                | messages (bot tok)  |   DiscordClient bot token     |
   |                |<--------------------|                               |
   | "todo-list-a1b2 is ready: https://…/tasks/preview-app/todo-list-a1b2/"
```

## Components

### 1. tasks service — new `mcp-servers/tasks/routes_aiuibuilder.py`

`APIRouter(prefix="/api/aiuibuilder")`, mounted in `main.py`. Distinct prefix
(not `/api/projects` or `/api/tasks`) so it can't collide with their
`/{slug}`/`/{task_id}` catch-alls.

**`POST /api/aiuibuilder/build`** — `current_user` (X-User-Email; **no admin gate**)
- Body: `BuildRequest { description: str (1–4000), name: str | None }`.
- Concurrency guard (see below): if any `BUILD` task is in a live state, raise `429`.
- Generate a unique slug from `name or description` (see Slug generation).
- Create a `TaskItem`:
  - `action_type="BUILD"`, `assignee_email = user.email`,
    `assignee_name = user.email.split("@")[0]`,
  - `description = <user description>` (trimmed to 20 000 chars, same cap as web),
  - `built_app_slug = slug` (set up front so status-by-id/slug works immediately and
    the owner-insert on completion is keyed correctly),
  - `status="running"`, `mode="ai"`, `max_attempts=3` (quality loop — auto-retry +
    VERIFY; also yields a clean terminal `failed` rather than `pending`),
  - `priority="NICE_TO_HAVE"`, synthetic `meeting_id=uuid4()`.
- Scaffold the empty app skeleton on disk by reusing
  `routes_tasks._ensure_app_skeleton(slug, storage=None)` (best-effort; disk failure
  doesn't block).
- Create a `TaskExecution(status="running")`, register `_RUNNING[task_id]`, and
  `asyncio.create_task(_run_execution(task_id, exec_id, prompt))` where `prompt =
  claude_executor.build_prompt(description=…, action_type="BUILD", priority=…,
  meeting_title=str(meeting_id), meeting_date="", supabase_url=None, has_db_uri=False,
  slug=slug, user_email=user.email)`.
- Return `201 BuildResponse { task_id: str, slug: str, status: "running" }`.

**`GET /api/aiuibuilder/build/{task_id}`** — `current_user`
- Load the task; `404` if missing. Ownership: caller's email must equal the task's
  `assignee_email` (else `404`, not `403`, to avoid leaking existence).
- Map internal task status → a small public status:
  - `running`, `planning`, `awaiting_input` → `"running"`
  - `completed` → `"completed"`
  - `failed` → `"failed"`
  - any other (`pending`, `claimed_manual`, …) → `"running"` (defensive; shouldn't
    occur for a `max_attempts=3` build, which terminates as `completed`/`failed`).
- Return `BuildStatusResponse { status, slug, preview_url, error }`:
  - `preview_url = https://<AIUI_PUBLIC host>/tasks/preview-app/<slug>/` only when
    `status=="completed"` (built via the existing `_public…`/env host helper or a
    small local helper using `AIUI_PUBLIC_DOMAIN`), else `null`.
  - `error` = truncated `task.result` when `status=="failed"`, else `null`.

No new DB tables or migrations — everything reuses `tasks.items` / `tasks.executions`
/ `tasks.project_members`.

### 2. tasks service — `main.py`
`from routes_aiuibuilder import router as aiuibuilder_router` and
`app.include_router(aiuibuilder_router)`. Order is irrelevant — the prefix is unique.

### 3. webhook-handler — `clients/tasks.py`
Add two methods (X-User-Email only, via the existing `_request` helper, so the
"never send the cron secret" guarantee is structural):
- `start_build(user_email, description, name=None) -> dict` → `POST /api/aiuibuilder/build`.
- `get_build_status(user_email, task_id) -> dict` → `GET /api/aiuibuilder/build/{task_id}`.

### 4. webhook-handler — `clients/discord.py`
Add `post_channel_message(channel_id, content) -> bool`:
- `POST {DISCORD_API_BASE}/channels/{channel_id}/messages` with header
  `Authorization: Bot {bot_token}`, body `{"content": content[:2000]}`.
- Needed because the existing `followup_message`/`edit_original` use the **interaction
  token**, which expires 15 minutes after the command — a build can run longer. The
  channel-message path uses the bot token and works indefinitely (requires the bot to
  have Send Messages in the channel).
- Returns `True` on 200/201, logs and returns `False` otherwise. Never raises.

### 5. webhook-handler — `handlers/commands.py`
- `CommandContext` gains an optional field `notify_channel: Callable[[str],
  Awaitable[None]] | None = None` — a platform-supplied "post a fresh message to this
  channel" callback (distinct from `respond`, which edits the deferred reply).
- `_handle_aiuibuilder` gains a `build` branch:
  - Require the user be mapped (same `discord_user_email_map` gate as `list`/`status`).
  - Parse args with `shlex`; `build` needs exactly one quoted description
    (`build "<description>"`). Missing/empty → usage hint. Optional second token is
    treated as a `name`.
  - Call `tasks_client.start_build(email, description, name)`.
  - `respond("Building `<slug>` … I'll post the link here when it's ready (usually a
    few minutes).")`.
  - If `ctx.notify_channel` is set, `asyncio.create_task(self._watch_build(ctx, email,
    task_id, slug))`; otherwise skip the watcher (e.g. voice/Slack paths) — the build
    still runs and is reachable via `status`.
- `_watch_build(ctx, email, task_id, slug)`:
  - Poll `tasks_client.get_build_status(email, task_id)` every `POLL_SECONDS` (≈12),
    up to `MAX_POLLS` (≈150 → ~30 min).
  - Tolerate transient `TasksAPIError` (network/5xx): log, keep polling, give up only
    after several consecutive failures.
  - On `completed`: `notify_channel("`<slug>` is ready: <preview_url>")`.
  - On `failed`: `notify_channel("Build failed for `<slug>`. Open the App Builder to
    retry.")`.
  - On timeout: `notify_channel("`<slug>` is still building — check `/aiui aiuibuilder
    status <slug>`.")`.
- Map `start_build` errors via the existing `_format_tasks_error`, adding a `429`
  case → "A build is already running — try again in a few minutes."
- Add `build` to the `aiuibuilder` usage string and to `_handle_help`.

### 6. webhook-handler — `handlers/discord_commands.py`
When constructing `ctx`, also set:
```python
async def notify_channel(msg: str) -> None:
    await self.discord.post_channel_message(channel_id, msg)
ctx.notify_channel = notify_channel
```
(only when `channel_id` is present). Existing `respond` (edit deferred) is unchanged.

## Memory & Concurrency

- **One build at a time, platform-wide.** Before creating the task, `POST /build`
  checks for any `TaskItem` with `action_type="BUILD"` and
  `status IN ('running','planning','awaiting_input')`; if found, raise `429` with
  detail "A build is already running." This is the honest constraint for a 3.8 GB
  server with a single agent VM, and prevents a second concurrent agent run from
  triggering the OOM cascade noted in the orphan-reap comment in `main.py`.
- The check + insert run inside one `session()` transaction guarded by a
  transaction-scoped advisory lock (`pg_advisory_xact_lock(hashtext('aiuibuilder:build'))`)
  so two near-simultaneous Discord builds can't both pass the guard.

## Security

- **X-User-Email only, end to end.** `TasksClient._headers` already returns only
  `{"X-User-Email": …}`; the new methods reuse it. No admin header, no cron secret.
- **New endpoints are `current_user`, not `current_admin`.** The build task is owned
  by the caller; `GET /build/{id}` enforces `assignee_email == caller` and returns
  `404` (not `403`) on mismatch so project existence isn't leaked across users.
- **Slug is validated** against the existing `_SLUG_ROUTE_RE`
  (`^[a-z0-9][a-z0-9-]{1,80}$`) before any filesystem use — no path traversal.
- **Description is data, not a command.** It is interpolated into `build_prompt` and
  handed to the Claude agent, which runs in the isolated VM behind the enforced Squid
  egress — identical trust boundary to the web build. No shell interpolation.
- **No secrets in responses or logs.** The build-status payload is
  `{status, slug, preview_url, error}`; `error` is a truncated, already-scrubbed
  `task.result`. The watcher logs task ids/slugs, never tokens.
- **`.env` and credentials** are untouched by this change.

## Slug generation

`_make_slug(name_or_description) -> str`:
1. Lowercase; take from `name` if given else the first ~6 words of `description`.
2. Replace non-`[a-z0-9]` runs with `-`; strip leading/trailing `-`; collapse repeats;
   cap base length (~40 chars). Fallback base `"app"` if empty.
3. Append `"-" + secrets.token_hex(2)` (4 hex chars) for uniqueness.
4. Verify the final slug matches `_SLUG_ROUTE_RE` and is unused across
   `tasks.items.built_app_slug`, `tasks.published_apps.slug`,
   `tasks.project_members.slug` (mirrors the rename collision check); regenerate the
   suffix on the rare clash (bounded retries).

## Error handling

- All tasks↔webhook HTTP calls go through `TasksClient._request`, which raises
  `TasksAPIError(status=0, …)` on network failure and `TasksAPIError(status, detail)`
  on 4xx/5xx. The `build` branch maps these to friendly Discord text and never leaks
  raw bodies (reuses `_format_tasks_error` + the new `429` case).
- `_watch_build` is defensive: transient errors don't kill the loop; a terminal
  give-up always posts *something* actionable.
- `post_channel_message` and the agent spawn are wrapped; a failed Discord post is
  logged, not raised (the build already happened).
- `_ensure_app_skeleton` failures are swallowed (the agent recreates the dir) — same
  as the web create path.

## Testing (TDD, all green)

**tasks service (`mcp-servers/tasks/tests/`):**
- `_make_slug`: shape, lowercasing, suffix, fallback, collision → regenerate.
- `POST /build`: happy path creates a `BUILD` task owned by the caller, scaffolds,
  and spawns execution — with `_run_execution` / executor **mocked** so no real agent
  runs. Asserts response shape + that the task row is `running` with the slug set.
- `POST /build` concurrency: a pre-existing `running` BUILD task → `429`.
- `GET /build/{id}`: owner sees mapped status + `preview_url` on completed; non-owner
  → `404`; unknown id → `404`; missing X-User-Email → `401`.

**webhook-handler (`webhook-handler/tests/`):**
- `TasksClient.start_build` / `get_build_status` via `respx`: correct method/path/body
  and **`X-User-Email` present, `X-Cron-Secret` absent**.
- `DiscordClient.post_channel_message` via `respx`: hits `/channels/{id}/messages`
  with `Authorization: Bot …`; truthy/falsey on 200/4xx.
- `_handle_aiuibuilder` `build` branch: unmapped user rejected; missing description →
  usage; happy path calls `start_build` and replies "Building"; `429` → "already
  running" text.
- `_watch_build`: with a fake `tasks_client` returning `running → completed`, asserts
  `notify_channel` is called once with the preview URL; `running → failed` → failure
  text; uses a patched/short poll interval (no real sleeps).

**Layer-2 e2e (`test_discord_e2e_local.py` pattern):**
- A signed Discord interaction `aiuibuilder build "a todo app"` reaches
  `TasksClient.start_build` with `X-User-Email` only and no cron secret (respx,
  ASGITransport, held-open poll loop — same harness as the existing cronjob e2e).

## Deployment

Per the established Workflow A (no git on the server): `scp` the changed files to
`/root/proxy-server/`, then rebuild only the two affected services:
`docker compose -f docker-compose.unified.yml up -d --build tasks webhook-handler`,
then `/healthz` smoke. No new env vars, no new command registration (the
`aiuibuilder` subcommand already takes a single free-text `args` string — `build` is
just another parsed action).
