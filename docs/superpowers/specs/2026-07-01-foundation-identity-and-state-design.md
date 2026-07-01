# Foundation: one identity + durable state + safety — design

Date: 2026-07-01
Branch: `feat/just-chat-intent-router`
Status: approved (design), pending implementation
Sub-project 1 of 4 (audit follow-up). Next: everything-from-chat, my-workspace, slack-catch-up.

## Problem

A full audit of both bots surfaced a cluster of real bugs under the shiny features:

1. **Split-brain identity.** build/schedule/connectors resolve a user via
   `_resolve_email_auto` (falls back to a synthetic `discord-<id>@aiui.local`),
   while briefing/apps use `_resolve_email_for_ctx` (real email, else "not
   linked"). The same user can build but is told "not linked" for briefing/apps.
2. **Connector connect-loop.** The Gmail/Drive token binds (via `connect_url`'s
   signed state) to whatever identity was used at connect time; a different
   identity is checked later by `is_connected`, so "Connect Gmail" never makes
   `/aiui email` or the briefing's email line work.
3. **Ephemeral conversational state.** `_pending_intents`, `_pending_clarify`,
   `_user_app_slug` live in memory on the router and are lost on every deploy:
   "Yes, do it" → "that request expired"; a clarify reply is misread as new; and
   losing `_user_app_slug` silently downgrades "add a contact form" in a thread
   from an enhance to a plain answer.
4. **SSRF gap.** User-supplied URLs (video capture / URL paste) reach the
   headless browser with no private/loopback/metadata blocking.

## Decisions (from brainstorming)

- **Require a real linked account everywhere** (one identity, no synthetic
  fallback).
- **Full state persistence in the tasks database** (a generic key/value store).
- Fold in the two cheapest safety wins: a container memory limit and the SSRF
  guard, plus a concurrency guard on the classification path.

## Architecture

The webhook-handler has no DB of its own; it talks to the tasks service over HTTP
(`X-User-Email` for user data, `X-Internal-Secret` for system endpoints). The
tasks service owns Postgres, the Discord link store (`routes_discord_links.py`),
and boot-time `.sql` migrations (`db.py::_run_migrations`). We extend that.

### Component 1 — One identity, required everywhere (webhook-handler only)

- Every flow resolves identity through the single `_resolve_email_for_ctx` path:
  - Slack → profile email via `users:read.email`.
  - Voice → `VOICE_USER_EMAIL`.
  - Discord → the link store (`_resolve_email` → static map, then
    `tasks_client.resolve_link`).
- Remove the synthetic fallback: delete `_resolve_email_auto` and switch its
  call sites (the Discord schedule + connector-gate flows in
  `discord_commands.py`, and any `commands.py` caller) to `_resolve_email_for_ctx`
  (via a ctx). Unlinked → the existing self-service **Link** card on Discord
  (`_respond_not_linked`) / not-linked guidance on Slack.
- Effect: bug #1 gone; connect, `is_connected`, and task-runs all key on the same
  real email, so bug #2 (connect-loop) is gone and the briefing email line works
  once Gmail is connected.
- Migration note: apps/schedules previously created under a synthetic email stay
  owned by it. The team already uses real mapped emails, so only previously
  unlinked channel users must link once. Placeholder link rows (created by the
  thread setters) are unaffected. This is documented, not auto-migrated.

### Component 2 — Durable conversational state (tasks Postgres + webhook-handler)

Tasks service:
- `migrations/029_bot_state.sql`:
  `CREATE TABLE IF NOT EXISTS tasks.bot_state (state_key text PRIMARY KEY, value
  jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), expires_at
  timestamptz NULL);` plus `CREATE INDEX IF NOT EXISTS ix_bot_state_expires ON
  tasks.bot_state (expires_at);`
- `models.py`: `class BotState(Base)` — `__tablename__ = "bot_state"`,
  `__table_args__ = {"schema": "tasks"}`, `state_key Text pk`, `value JSONB`,
  `updated_at`, `expires_at` (nullable), matching the existing `Column(...)` style.
- `routes_state.py`: `APIRouter(prefix="/state")`, `_require_internal(x_internal_secret)`
  (identical to `routes_discord_links.py`), authed by `X-Internal-Secret`:
  - `GET /state/{key}` → `{"value": <jsonb> | null}`; treats a row with
    `expires_at < now()` as absent (returns null).
  - `PUT /state/{key}` body `{"value": <any>, "ttl_seconds": <int|null>}` →
    upsert `value`, `updated_at = now()`, `expires_at = now()+ttl` when given.
  - `DELETE /state/{key}` → delete (idempotent).
  - Register the router in `main.py`.

Webhook-handler:
- `TasksClient.get_state(key)`, `set_state(key, value, ttl_seconds=None)`,
  `delete_state(key)` via `_internal_request` (mirrors the discord-links methods).
- `handlers/state_store.py::StateStore` — a thin async wrapper over those with a
  write-through in-memory cache: `get/set/delete(key, ...)`. On `TasksAPIError`
  it logs once and degrades to in-memory only (never breaks a chat turn).
  Namespacing helpers: `pending_intent:<token>`, `pending_clarify:<platform>:<uid>`,
  `current_app:<platform>:<uid>`.
- `CommandRouter` uses `StateStore` for `_pending_intents` / `_pending_clarify`
  (TTL ~1800s) and current-app (no TTL). The in-memory dicts become the cache
  layer inside `StateStore`, not fields on the router, so a restart re-reads from
  Postgres. `park_intent`/`peek_intent`/`cancel_intent`, `plan_chat_step`, and
  `handle_builder_thread_message` become `async` where they touch state (they are
  already awaited in async paths).

### Component 3 — Safety (cheap, high value)

- `docker-compose.unified.yml`: add `deploy.resources.limits.memory: 512M` (with a
  reservation) to the webhook-handler service. Drift-check the server compose
  first (prod compose may be ahead); never touch `.env`.
- `handlers/url_guard.py::is_safe_public_url(url) -> bool` — https-only; resolve
  host and reject private/loopback/link-local/ULA and `169.254.169.254`. Apply at
  the URL entry points: `run_video_capture`, `video_intake.handle_url_paste`, and
  the `/video add` path. On reject, a friendly "I can only capture public https
  sites" message.
- A module-level `asyncio.Semaphore` (e.g. 8) acquired around the classify call in
  the gateway chat path (`video_intake.handle_chat` → `handle_chat_message`), so a
  burst of channel messages can't spawn unbounded concurrent LLM calls.

## Testing

Unit (pure-first):
- Identity: `_resolve_email_for_ctx` per platform; a build/schedule with an
  unlinked Discord user calls `_respond_not_linked` (no synthetic email); confirm
  `_resolve_email_auto` is gone / unused.
- `StateStore`: set/get/delete round-trip against a fake TasksClient; TTL passed
  through; cache hit avoids a second call; `TasksAPIError` degrades to in-memory.
- Tasks `/state` endpoints: internal-secret required (403 without); PUT→GET
  round-trip; expired row reads as null; DELETE idempotent. (pytest under the
  tasks service's `AIUI_TEST_DB=1` harness.)
- `is_safe_public_url`: allow/block table (public https allowed; http, private,
  loopback, link-local, metadata blocked).
- Concurrency guard: N concurrent chat messages never exceed the cap.

Live in-container e2e (real gpt-5 + real tasks):
- Unlinked Discord user → build shows the Link card; linked user → build runs.
- State survives a "restart": write a pending intent via one router instance,
  read it via a fresh instance (both against the real `/state`).
- Connect Gmail under the unified identity → `is_connected` returns true for the
  same email used by the briefing.
- `is_safe_public_url` blocks `http://169.254.169.254/...`.

## Deploy

Two services, tasks first:
1. **tasks:** new migration + `routes_state.py` + `BotState`. Prune dangling
   images first (box has hit 95%); drift-check every file CRLF-normalized and
   NEVER overwrite `templates.py` (server is ahead). Rebuild; the migration runs
   idempotently on boot. Verify `https://ai-ui.coolestdomain.win/tasks/healthz`.
2. **webhook-handler:** per-file scp (never `scp -r`) of the changed handlers +
   client; rebuild; verify `Up (healthy)` + gateway reconnect.
Commit on `feat/just-chat-intent-router`; push to fork (gh switch, fetch+rebase,
no force). Never touch `.env`.

## Out of scope (fast-follows / later sub-projects)

- Rebind synthetic→real ownership on link-approve (migrate old synthetic apps).
- Per-user rate limit and full interaction/message idempotency (LRU of processed
  ids) — the concurrency guard is the v1 slice.
- Persisting the discord/slack `_pending_schedules` connector-gate dicts (reuse
  `StateStore` in a later pass).
