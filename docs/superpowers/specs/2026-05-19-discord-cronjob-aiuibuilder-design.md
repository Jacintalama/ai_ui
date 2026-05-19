# Discord `/aiui cronjob` and `/aiui aiuibuilder` subcommands — Design

**Date:** 2026-05-19
**Author:** Claude (paired with Jacinta)
**Status:** Draft for review
**Branch:** `feat/vm-agent-flight-mcp`

## Goal

Lukas asked: "connect all commands like /aiuibuilder, /cronjob, /mcp server — all of that. He says next will be the AIUI, so it can become a bot."

The existing Discord `/aiui` slash command already exposes 17 subcommands (`ask`, `mcp`, `workflow`, `pr-review`, etc.). This spec adds two more:

- **`/aiui cronjob`** — list / create / delete user-scoped cron schedules.
- **`/aiui aiuibuilder`** — list / status / open the user's published apps from the App Builder.

These let a Discord user manage their own schedules and apps without leaving Discord.

## Non-Goals

- New top-level slash commands (`/cronjob`, `/aiuibuilder`). User chose subcommands under `/aiui`.
- Account-linking flow with OAuth. v1 uses a static env-var map (`DISCORD_USER_EMAIL_MAP`) and rejects unmapped users with a "ask Lukas to add you" message.
- Pagination of cron lists. v1 truncates the Discord reply at 2000 chars and appends `... +N more` when needed.
- Migrating away from the older webhook-handler `/scheduler` engine. The new schedules live in the tasks service (`/api/tasks/schedules`); the legacy one stays where it is, untouched by this work.

## Architecture

```
Discord user      Discord                webhook-handler                tasks
   |                |                         |                          |
   |  /aiui cronjob |                         |                          |
   | create "0 8 *  |                         |                          |
   |  * *" "foo"    |                         |                          |
   |--------------> |                         |                          |
   |                |  POST /webhook/discord  |                          |
   |                |  (Ed25519 signed)       |                          |
   |                |-----------------------> |                          |
   |                |                         | verify_discord_signature |
   |                |                         | parse subcommand         |
   |                |                         | DEFERRED ack (5)         |
   |                |  type=5                 |                          |
   |                | <---------------------- |                          |
   |                |                         | _handle_cronjob          |
   |                |                         | map discord_id → email   |
   |                |                         |  via env-var dict        |
   |                |                         |                          |
   |                |                         | POST tasks:8210/schedules|
   |                |                         | X-Cron-Secret: <env>     |
   |                |                         | X-User-Email: <mapped>   |
   |                |                         |-------------------------> |
   |                |                         |       201 + body         |
   |                |                         | <-------------------------|
   |                |                         |                          |
   |                | PATCH @original         |                          |
   |                | (followup with content) |                          |
   |                | <---------------------- |                          |
   |  visible reply |                         |                          |
   | <------------- |                         |                          |
```

**Key boundaries**
- webhook-handler authenticates the Discord request via Ed25519. It then calls tasks **directly** (`tasks:8210`) over the Docker network using the dual-auth pattern: `X-Cron-Secret` (operator-level, env-injected) **and** `X-User-Email` (the mapped end-user). The Caddy `request_header -X-User-Email` strip only applies to public `/tasks/schedules*` traffic — internal container-to-container traffic is trusted.
- No api-gateway hop. The api-gateway exists to translate JWTs to `X-User-Email`; webhook-handler already knows the email from its mapping, so the gateway adds nothing.
- The tasks service applies its own ownership-scoped 404 on cross-user access. Even if the mapping table is wrong, a user can never see another user's schedules.

## Component changes

### 1. `webhook-handler/config.py` — new setting

```python
discord_user_email_map: dict[str, str] = {}  # discord_id -> email
```

Parsed from `DISCORD_USER_EMAIL_MAP` env var: comma-separated `<id>:<email>` pairs.
Empty / unset → empty dict → all `cronjob` / `aiuibuilder` calls return the "not linked" reply.

### 2. `webhook-handler/clients/tasks.py` — new HTTP client

Thin wrapper around httpx.AsyncClient with two methods used in v1:

```python
async def list_schedules(user_email: str) -> list[dict]
async def create_schedule(user_email: str, cron: str, prompt: str) -> dict
async def delete_schedule(user_email: str, schedule_id: str) -> bool
async def list_projects(user_email: str) -> list[dict]
async def get_project_status(user_email: str, slug: str) -> dict
```

Each method sends `X-Cron-Secret` + `X-User-Email`. Failure modes: returns `None`/raises a typed `TasksAPIError` with `(status, message)` the dispatcher maps to friendly Discord text.

### 3. `webhook-handler/handlers/commands.py` — two new dispatchers

```python
async def _handle_cronjob(self, ctx: CommandContext) -> None
async def _handle_aiuibuilder(self, ctx: CommandContext) -> None
```

Each:
1. Resolves `discord_id → email` via `settings.discord_user_email_map`. Unmapped → friendly reply, return.
2. Splits `ctx.arguments` with `shlex.split` to honour quotes.
3. Dispatches on first token (`list`, `create`, `delete` etc.). Unknown action → usage hint.
4. Calls `clients.tasks.TasksClient` method. Catches `TasksAPIError`, maps to user-readable text.
5. Truncates reply to 2000 chars before `ctx.respond`.

`CommandRouter.parse_command()` adds `cronjob`, `aiuibuilder` to `known_commands`. `_handle_help()` text updated.

### 4. `mcp-servers/tasks/routes_projects.py` — new `GET /api/projects` endpoint

Currently the router only has per-slug routes. Add:

```python
@router.get("", response_model=list[ProjectSummary])
async def list_my_projects(user: AdminUser = Depends(current_admin)) -> list[ProjectSummary]:
    """List projects where the caller is a member."""
```

Scans the apps directory, filters via the existing `_user_can_see_project(s, slug, email)`. Returns slug, name, member role, publish status, public URL if published.

### 5. `scripts/register_discord_commands.py` — idempotent registration

Adds `cronjob` and `aiuibuilder` to the `/aiui` subcommand list, PUTs to Discord API. Re-runnable. Reads `DISCORD_APPLICATION_ID` and `DISCORD_BOT_TOKEN` from env.

### 6. `webhook-handler/handlers/discord_commands.py` — quoted args

The current `_parse_options` returns `(subcommand, single_value_string)`. That works because Discord delivers each option as a separate field. For `cronjob create "0 8 * * *" "summarize my emails"` we want both values preserved with their quotes. Simplest path: change the Discord application command to accept a single `args` string option per subcommand and parse it with `shlex` in the dispatcher. This avoids redesigning the option parser.

## Auth model

| Step | Who is authenticated | How |
|------|----------------------|-----|
| Discord → webhook-handler | Discord platform | Ed25519 (already implemented) |
| webhook-handler → tasks | webhook-handler operator | `X-Cron-Secret` (env, dual-auth path) |
| identity inside tasks | end user | `X-User-Email` (mapped from Discord ID) |

The mapping table is the only place trust is established between Discord identity and tasks user identity. It's an env var, owned by ops. There is no self-service link flow in v1.

## Error UX

| User-visible reply | Trigger |
|---|---|
| "Your Discord account isn't linked. Ask Lukas to add you." | discord_user_id not in `DISCORD_USER_EMAIL_MAP` |
| "Usage: `/aiui cronjob <list\|create\|delete>`" | empty or unknown action |
| "Need 2 args: `create \"<cron>\" \"<prompt>\"`" | create with <2 tokens after shlex |
| "Invalid cron: ..." | tasks returns 400 from cron parser |
| "Min interval is 5 min." | tasks returns 400 from interval guard |
| "You hit the max ({N}) schedules." | tasks returns 400 from quota guard |
| "No such schedule: {id}" | tasks returns 404 |
| "Tasks service unreachable, try again." | httpx ConnectError or 5xx |

No reply ever contains: the cron secret, `X-Cron-Secret` header, the full email map, or any other email besides the caller's own.

## Testing strategy

**Layer 1 — unit (must be green before SCP):**
- `webhook-handler/tests/test_command_router.py` — `parse_command` recognises `cronjob` and `aiuibuilder`.
- `webhook-handler/tests/test_cronjob_handler.py` — new; mocks `tasks.TasksClient` via respx, asserts: unmapped user → friendly reject, mapped user list returns formatted reply, create with missing args → usage hint, create with valid args → calls tasks and replies success, delete propagates 404.
- `webhook-handler/tests/test_aiuibuilder_handler.py` — analogous.
- `mcp-servers/tasks/tests/test_routes_projects_list.py` — `GET /api/projects` returns only projects where caller is member.

**Layer 2 — integration (must be green before announcing):**
- `scripts/discord_e2e.sh`:
  1. POST tasks `/schedules` directly with X-Cron-Secret + a test email → expect 201.
  2. Build a synthetic Discord interaction payload, sign it with the deployed Ed25519 public key (signing is asymmetric; we use the matching private key only available on dev side, so this step is local-only).
  3. POST synthetic payload to `webhook-handler:8086/webhook/discord` → expect 200 with type 5.
  4. Poll a temporary debug endpoint or assert via logs that the followup PATCH was issued.
  5. Delete the test schedule.

**Layer 3 — real Discord (manual, takes 60 seconds):**
1. `/aiui help` — shows `cronjob` and `aiuibuilder` in the help text.
2. `/aiui cronjob list` — replies "no schedules" or a list.
3. `/aiui cronjob create "*/5 * * * *" "ping"` — confirms create with returned id.
4. `/aiui cronjob delete <id>` — confirms delete.
5. `/aiui aiuibuilder list` — confirms projects route.

## Deploy plan

1. Run Layer 1 locally — must be green.
2. SCP changed files to `/root/proxy-server/`.
3. `docker compose -f docker-compose.unified.yml up -d --build webhook-handler tasks` on Hetzner.
4. `python3 scripts/register_discord_commands.py` from inside the webhook-handler container (or any host with the token).
5. Run Layer 2 from a dev shell pointing at the live server. Discord interactions to live `/webhook/discord` skipped if local Ed25519 priv key isn't available — fall back to local webhook-handler-only test.
6. Manual Layer 3 from Discord.

Rollback: same SCP/build with previous commit if anything goes wrong. The env-var map is the only non-code state; resetting it is trivial.

## Open questions

None blocking. Pagination, OAuth account-linking, and migrating off the legacy webhook-handler scheduler can each be follow-ups.

## Out of scope (deferred)

- A `/link` slash command for end users to bind their own Discord ID to their email. Requires a verification round-trip (email a code, user types it). Worth it once we have >5 users.
- Pagination of `cronjob list` past 2000-char Discord limit (multi-message followup with `followup_message` not `edit_original`).
- Replacing the legacy webhook-handler `/scheduler` engine. Two cron engines is duplicative but each serves a different purpose right now (legacy = n8n workflow triggers; new = LLM-prompt schedules).
