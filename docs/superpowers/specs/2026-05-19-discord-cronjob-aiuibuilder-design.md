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
- **Per-argument typed Discord options for cronjob/aiuibuilder.** Discord supports `type=1` subcommands with multiple typed sub-options (one for `cron`, one for `prompt`, each with autocomplete + length validation). The spec uses a single free-text `args` option per subcommand and parses it with `shlex` server-side. This is a deliberate UX regression for v1 — it shortens implementation by ~half a day and lets us iterate on the parser without re-registering the command tree. Worth revisiting once we know which subcommands users invoke most.
- Rate limiting webhook-handler → tasks calls. A Discord client spamming `cronjob list` would hammer tasks; in practice Discord enforces a 3 req/sec per-application limit so spam-from-Discord caps itself. If we ever expose webhook-handler outside Discord this needs revisiting.

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
- webhook-handler authenticates the Discord request via Ed25519. It then calls tasks **directly** (`tasks:8210`) over the Docker network sending ONLY `X-User-Email: <mapped-email>` — no `X-Cron-Secret`. This is critical: in `routes_schedules._resolve_caller`, presenting the cron secret flips `is_operator=True` and the list/read path then skips the `user_email` filter, returning ALL schedules across users. By withholding the cron secret, webhook-handler hits the end-user path and `_scoped_schedule` enforces the 404-on-other-user check. The mapping table is the perimeter trust: if it's wrong, a user sees the wrong account's data, but a Discord user can never escalate to see ALL data.
- The Caddy `request_header -X-User-Email` strip only applies to public `/tasks/schedules*` traffic — internal container-to-container traffic on the Docker network is trusted because Caddy is the only path from the public Internet to internal services, and Caddy strips that header on the public path.
- No api-gateway hop. The api-gateway exists to translate JWTs to `X-User-Email`; webhook-handler already knows the email from its mapping, so the gateway adds nothing.
- The tasks service applies its own ownership-scoped 404 on cross-user access via `_scoped_schedule`. Even if the mapping table is wrong, a user can only ever see one wrong account — never all accounts.

## Component changes

### 1. `webhook-handler/config.py` — new setting

```python
discord_user_email_map: dict[str, str] = {}  # discord_id -> email
```

Parsed from `DISCORD_USER_EMAIL_MAP` env var: comma-separated `<id>:<email>` pairs.
Empty / unset → empty dict → all `cronjob` / `aiuibuilder` calls return the "not linked" reply.

### 2. `webhook-handler/clients/tasks.py` — new HTTP client

Thin wrapper around httpx.AsyncClient:

```python
async def list_schedules(user_email: str) -> list[dict]
async def create_schedule(user_email: str, name: str, cron: str, prompt: str, tz: str = "Asia/Manila") -> dict
async def delete_schedule(user_email: str, schedule_id: str) -> bool
async def list_projects(user_email: str) -> list[ProjectSummary]
async def get_project_status(user_email: str, slug: str) -> ProjectStatus
```

Each method sends ONLY `X-User-Email: <user_email>` — no `X-Cron-Secret` — so the tasks service walks the end-user code path with ownership scoping. Failure modes: raises a typed `TasksAPIError(status, message)` the dispatcher maps to friendly Discord text.

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

### 4. `mcp-servers/tasks/auth.py` — new `current_user` dep

`current_admin` (lines 13-24) raises **403** unless BOTH `X-User-Email` AND `X-User-Admin: true` are present. We need a non-admin sibling for endpoints that list-the-caller's-own-things:

```python
@dataclass(frozen=True)
class CurrentUser:
    email: str

def current_user(request: Request) -> CurrentUser:
    """Same as current_admin but no admin gate. Used by list-my-* endpoints."""
    email = request.headers.get("x-user-email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Missing X-User-Email")
    return CurrentUser(email=email)
```

### 5. `mcp-servers/tasks/routes_projects.py` — new endpoints

Currently the router only has per-slug routes, all admin-gated. Add two non-admin endpoints:

```python
@router.get("", response_model=list[ProjectSummary])
async def list_my_projects(user: CurrentUser = Depends(current_user)) -> list[ProjectSummary]:
    """List projects where the caller is a member."""

@router.get("/{slug}/status", response_model=ProjectStatus)
async def get_my_project_status(slug: str, user: CurrentUser = Depends(current_user)) -> ProjectStatus:
    """Membership + publish status for one project, scoped to caller."""
```

Both call the existing `_user_can_see_project(s, slug, email)` helper; cross-user access returns 404, never 403, so existence isn't leaked.

**Response schemas:**

```python
class ProjectSummary(BaseModel):
    slug: str
    name: str
    role: str            # "owner" | "editor" | "viewer"
    published: bool
    public_url: str | None  # only set when published

class ProjectStatus(ProjectSummary):
    last_commit_at: str | None      # ISO 8601
    last_commit_message: str | None
    custom_domain: str | None
```

### 6. `scripts/register_discord_commands.py` — idempotent registration

Discord's `PUT /applications/{app_id}/commands` REPLACES the full command list — partial updates are not supported. The script must therefore re-PUT the **complete** `/aiui` subcommand tree (all 19 subcommands: the 17 existing + `cronjob` + `aiuibuilder`), not just the 2 new ones. Re-runnable. Reads `DISCORD_APPLICATION_ID` and `DISCORD_BOT_TOKEN` from env.

### 7. `webhook-handler/handlers/discord_commands.py` — quoted args

The current `_parse_options` returns `(subcommand, single_value_string)`. That works because Discord delivers each option as a separate field. For `cronjob create "0 8 * * *" "summarize my emails"` we want both values preserved with their quotes. Simplest path: change the Discord application command to accept a single `args` string option per subcommand and parse it with `shlex` in the dispatcher. This avoids redesigning the option parser.

## Auth model

| Step | Who is authenticated | How |
|------|----------------------|-----|
| Discord → webhook-handler | Discord platform | Ed25519 (already implemented) |
| webhook-handler → tasks | end user (via mapping) | `X-User-Email` only — no cron secret |
| identity inside tasks | end user | `X-User-Email` (mapped from Discord ID) |

Why no cron secret on the webhook-handler → tasks hop: presenting `X-Cron-Secret` flips `is_operator=True` in `routes_schedules._resolve_caller`, after which `list_schedules` skips the per-user filter and returns everyone's data. By withholding the secret we stay on the end-user code path, and `_scoped_schedule` enforces 404-on-other-user on every mutation.

The trust boundary that makes "X-User-Email only" safe: Caddy is the only public ingress and it strips `X-User-Email` on `/tasks/schedules*`. The api-gateway also strips client-provided `X-User-Email` before injecting its own. The Docker network itself is trusted — only services explicitly bound to host ports are reachable from outside, and `tasks:8210` is not.

The mapping table is the only place trust is established between Discord identity and tasks user identity. It's an env var, owned by ops. There is no self-service link flow in v1.

### Mapping-table validation (startup)

`config.py` parses `DISCORD_USER_EMAIL_MAP` once at startup and:

1. Skips entries where the Discord ID isn't all-numeric (Discord snowflake format).
2. Lowercases the email side.
3. Warns (logger.warning) if two Discord IDs map to the same email — that's almost always a typo and amounts to silent cross-user impersonation.
4. Logs only the count of valid entries, NEVER the contents.

Failed parses don't crash the service — they log and the entry is dropped, so a typo in one row doesn't take down the webhook handler.

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

Scope explicit: Layer 2 validates webhook-handler in isolation using a **test Ed25519 keypair**, not the live Discord public key. The script generates a keypair, configures the test container with the public half, signs the synthetic interaction with the private half. The live deployment's public key (from Discord's developer portal) is never exercised outside Layer 3 — only Discord itself can sign for that key.

- `scripts/discord_e2e_local.sh`:
  1. POST tasks `/schedules` with `X-User-Email: e2e-test@local` (no cron secret) → expect 201.
  2. Generate ephemeral Ed25519 keypair. Start webhook-handler with `DISCORD_PUBLIC_KEY` overridden to the test public key.
  3. Build a synthetic `APPLICATION_COMMAND` payload for `/aiui cronjob list`, sign it with the test private key.
  4. POST signed payload to `webhook-handler:8086/webhook/discord` → expect 200 with `{"type": 5}`.
  5. **Assert the tasks call happened**: pytest test wraps it with respx, asserting the dispatcher called `clients.tasks.list_schedules("e2e-test@local")` with exactly the mapped email. Not log-grepping — a respx mock that records the call.
  6. Delete the test schedule from step 1.

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
