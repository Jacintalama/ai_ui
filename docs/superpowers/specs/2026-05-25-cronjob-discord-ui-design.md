# Design: Button-Driven Cron Job Panel for Discord

- **Date:** 2026-05-25
- **Status:** Approved (design); pending implementation plan
- **Branch:** `feat/gdrive-gmail-connectors`
- **Author:** Ralph Benitez

## 1. Summary

Add a friendly, button-driven Discord UI for creating and managing scheduled
agent prompts ("cron jobs"). Today users must type a raw cron string
(`/aiui cronjob create "0 8 * * *" "summarize emails"`). This feature replaces
that with a pinned panel in a dedicated channel where the entire create + manage
flow is buttons, select-menus, and modals — no cron syntax required for common
cases.

The work lives **entirely in `webhook-handler`** (the Discord bot layer). It sits
on top of the existing `/schedules` REST API in `mcp-servers/tasks`, which
already supports create / list / delete / enable / disable / run-now. **No
backend (`mcp-servers/tasks`) changes are required.**

## 2. Goals

- Users create a schedule entirely via buttons + select-menus + one modal for the
  free-text prompt. No cron syntax for common cadences (daily / weekdays / weekly
  / hourly). A "Custom…" escape hatch accepts a raw cron expression.
- Full lifecycle management from a "My schedules" button: list, run-now,
  pause/resume, delete — mirroring the app-builder "Your apps" dropdown → per-item
  menu.
- A dedicated Discord channel (id `1508420480283967509`) with a pinned panel,
  set up idempotently by a script (mirrors `setup_app_builder_channel.py`).
- All interactions are ephemeral (visible only to the invoking user).

## 3. Non-Goals (out of scope for this iteration)

- **Result delivery**: posting the agent's output back to Discord when a job
  fires. The scheduler records `last_run_status` and persists `MEMORY.md`; the
  panel surfaces last-run status but does not deliver run output. (Noted as a
  follow-up; would require scheduler changes + storing a target channel/user.)
- **Timezone picker**: schedules default to `Asia/Manila` (the backend default
  and the operator's timezone). No per-schedule TZ selection in this iteration.
- **Persona field**: the backend supports a `persona`, but the panel leaves it at
  the default empty string for v1.
- Backend (`mcp-servers/tasks`) changes of any kind.

## 4. Existing Foundation (verified, not to be rebuilt)

### 4.1 Backend — `mcp-servers/tasks` (already present, uncommitted on VPS/local)
- `routes_schedules.py`: REST endpoints under `/schedules` and
  `/api/tasks/schedules`:
  - `GET /schedules` — list (scoped to caller's email for end-user calls)
  - `POST /schedules` — create (validates `cron_expr` via `croniter.is_valid`)
  - `DELETE /schedules/{id}`
  - `POST /schedules/{id}/enable`, `/disable`, `/run-now`
- Dual auth: operator (`X-Cron-Secret`) or end-user (`X-User-Email`, injected by
  the gateway). The bot uses the **end-user** path so schedules are user-owned.
- `scheduler.py`: 60-second tick loop, `croniter`-based matching, dedupe within a
  60s window, semaphore-bounded dispatch through the executor pipeline.
- `models.py` / `migrations/013_schedules.sql`: `tasks.schedules` table —
  `id, user_email, name, cron_expr, tz (default Asia/Manila), persona (default ''),
  prompt, enabled, last_run_at, last_run_status, created_at, updated_at`.
- Constraints surfaced by the API: minimum interval 5 minutes; a per-user quota.

### 4.2 Discord plumbing — `webhook-handler` (already present)
- `discord_commands.py` interaction dispatch. Interaction types:
  `PING`, `APPLICATION_COMMAND`, `MESSAGE_COMPONENT=3`, `MODAL_SUBMIT=5`,
  `MODAL=9`; response types include `DEFERRED_CHANNEL_MESSAGE=5`,
  `UPDATE_MESSAGE=7`.
  - `_handle_message_component` routes button/select clicks. Returns
    `{"type": 9, "data": <modal>}` to open a modal, or a deferred/update response.
  - `_handle_modal_submit` reads fields via `_extract_modal_value(data, field)`.
- `commands.py`: shared `CommandRouter` with `CommandContext` (carries
  `user_id`, `user_name`, `respond`, `respond_components`). Existing
  `_handle_cronjob` (text command) maps Discord user → email via
  `self._discord_user_email_map.get(ctx.user_id)` and calls the tasks client.
- `clients/tasks.py`: `list_schedules`, `create_schedule`, `delete_schedule`
  (end-user scoped; withholds the cron secret to stay user-scoped).
- `clients/discord.py`: `edit_original`, `followup_message`,
  `post_channel_message`, plus a generic `_request`.
- `scripts/setup_app_builder_channel.py`: idempotent channel find/create + pinned
  panel post (the template to mirror).
- `scripts/register_discord_commands.py`: registers `/aiui` subcommands;
  `cronjob` is already registered.

## 5. Design

### 5.1 New files

**`webhook-handler/handlers/cronjob_panel.py`** — pure functions only (no I/O),
mirroring `app_builder_panel.py`:
- Component builders:
  - `build_panel_payload()` → pinned panel content + two buttons
    (`cron:new`, `cron:list`).
  - `build_frequency_components()` → action row of buttons: Daily, Weekdays,
    Weekly, Hourly, Custom… (`cron:freq:<freq>`).
  - `build_dow_select(freq)` → string-select of Mon–Sun (`cron:dow:<dow>`),
    weekly only.
  - `build_hour_select(freq, dow=None)` → string-select of 24 hours
    (`cron:hour:<freq>[:<dow>]`), values `"0".."23"`.
  - `build_schedules_select(schedules)` → string-select of the user's schedules,
    value = schedule id, capped at 25 (Discord limit).
  - `build_schedule_menu(schedule)` → per-schedule status text + buttons:
    Run now (`cron:runnow:<id>`), Pause or Resume (`cron:pause:<id>` /
    `cron:resume:<id>`, chosen by `enabled`), Delete (`cron:delete:<id>`).
  - `build_delete_confirm(id)` → Confirm (`cron:delconfirm:<id>`) / Cancel
    (`cron:delcancel`).
  - `build_create_modal(cron_expr)` → modal `cron:create:<encoded_cron>` with
    fields: Name (optional, short), Prompt (required, paragraph).
  - `build_custom_cron_modal()` → modal `cron:customcron` with fields: Cron
    expression (required), Name (optional), Prompt (required).
- Cron-expression builder (pure, the testable core):
  - `cron_from_choice(freq, hour=None, dow=None) -> str`:
    - `daily`, hour H → `"0 H * * *"`
    - `weekdays`, hour H → `"0 H * * 1-5"`
    - `weekly`, dow D, hour H → `"0 H * * D"`
    - `hourly` → `"0 * * * *"`
- custom_id helpers: predicates (`is_cron_new`, `is_cron_list`,
  `is_schedule_select`, `is_cron_create_modal`, `is_custom_cron_modal`, …) and
  extractors (`freq_from_button`, `dow_from_select`, `hour_select_context`,
  `id_from_*`). Plus `encode_cron`/`decode_cron` round-tripping spaces ↔ `_`
  (cron expressions are short; custom_ids stay well under the 100-char limit).
- A human-readable formatter `describe_cron(cron_expr) -> str` for confirmations
  and the schedule menu (e.g. `"0 9 * * 1"` → "Mondays at 09:00"). For an
  expression it cannot humanize (e.g. an arbitrary custom cron such as
  `*/7 13 5 * *`), it falls back to echoing the raw cron string.

**`webhook-handler/scripts/setup_cronjob_channel.py`** — idempotent setup,
modeled on `setup_app_builder_channel.py`:
- Channel target: `CRONJOB_CHANNEL_ID` (defaults to `1508420480283967509`); if
  unset, find-or-create by `CRONJOB_CHANNEL_NAME` (default `cron-jobs`).
- Posts `build_panel_payload()` and pins it. Re-running reposts a fresh panel.
- Env: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`.

**Tests:** `webhook-handler/tests/test_cronjob_panel.py` (builders, parsers,
`cron_from_choice`, `encode/decode` round-trip, `describe_cron`) and
`webhook-handler/tests/test_cronjob_routing.py` (interaction routing + modal
submit).

### 5.2 Modified files

**`discord_commands.py`**
- `_handle_message_component`: add `cron:*` branches before the fallthrough.
  - `cron:new` → respond `UPDATE_MESSAGE` (type 7) with frequency buttons.
  - `cron:freq:daily|weekdays` → `UPDATE_MESSAGE` with hour select.
  - `cron:freq:weekly` → `UPDATE_MESSAGE` with day-of-week select.
  - `cron:freq:hourly` → return `MODAL` (type 9) `build_create_modal("0 * * * *")`.
  - `cron:freq:custom` → return `MODAL` `build_custom_cron_modal()`.
  - `cron:dow:<dow>` → `UPDATE_MESSAGE` with hour select carrying the day.
  - `cron:hour:<freq>[:<dow>]` → compute `cron_from_choice(...)` → return `MODAL`
    `build_create_modal(cron_expr)`.
  - `cron:list` → ephemeral deferred + background `run_cron_list`.
  - `cron:select` (value = id) → background `run_cron_menu(id)`.
  - `cron:runnow|pause|resume|delete|delconfirm|delcancel:<id>` → background
    `run_cron_*`. Delete shows the confirm row first; delconfirm performs it.
- `_handle_modal_submit`: add `cron:create:*` and `cron:customcron` branches.
  Extract `name` / `prompt` (and `cron` for custom) via `_extract_modal_value`,
  decode the cron from the custom_id (for `cron:create`), and run
  `run_cron_create` in the background with an ephemeral deferred ACK.
- All cron interaction responses use `flags=64` (ephemeral).

**`commands.py`** — thin orchestration methods on the router (call the tasks
client, format via `cronjob_panel` helpers, respond through the ephemeral
callbacks; all wrapped in try/except → `_friendly_schedule_error`):
- `run_cron_create(ctx, *, cron_expr, name, prompt)` — name auto-generated
  (`discord-{user}-{cron[:20]}`) if blank; **prompt is trimmed and rejected with a
  friendly message if blank/whitespace-only** (Discord's "required" check still
  passes whitespace); confirmation uses `describe_cron`.
- `run_cron_list(ctx)` — empty → friendly "no schedules yet"; else the
  schedules select.
- `run_cron_menu(ctx, schedule_id)` — fetch + render the per-schedule menu.
- `run_cron_runnow / run_cron_pause / run_cron_resume / run_cron_delete`.
- Update `_handle_help` text to mention the panel/channel.
- Existing `_handle_cronjob` text command kept unchanged as a fallback.

**`clients/tasks.py`** — add three end-user-scoped wrappers over existing
endpoints:
- `enable_schedule(user_email, schedule_id)` → `POST /schedules/{id}/enable`
- `disable_schedule(user_email, schedule_id)` → `POST /schedules/{id}/disable`
- `run_now_schedule(user_email, schedule_id)` → `POST /schedules/{id}/run-now`

### 5.3 custom_id scheme (`cron:` prefix)

| custom_id | trigger | action |
|---|---|---|
| `cron:new` | panel button | UPDATE → frequency buttons |
| `cron:freq:daily\|weekdays` | freq button | UPDATE → hour select |
| `cron:freq:weekly` | freq button | UPDATE → day-of-week select |
| `cron:freq:hourly` | freq button | open create modal (`0 * * * *`) |
| `cron:freq:custom` | freq button | open custom-cron modal |
| `cron:dow:<dow>` | weekly day select | UPDATE → hour select carrying `<dow>` |
| `cron:hour:<freq>[:<dow>]` | hour select | build cron → open create modal |
| `cron:create:<encoded_cron>` | modal submit | parse name+prompt → create |
| `cron:customcron` | modal submit | parse cron+name+prompt → create |
| `cron:list` | panel button | ephemeral schedules select |
| `cron:select` (value=id) | schedule select | per-schedule menu |
| `cron:runnow:<id>` | menu button | run-now directly (no confirm) → ▶️ triggered |
| `cron:pause:<id>` / `cron:resume:<id>` | menu button | disable/enable → refresh menu |
| `cron:delete:<id>` | menu button | show confirm row |
| `cron:delconfirm:<id>` / `cron:delcancel` | confirm | delete / dismiss |

### 5.4 Data flow

**Create:** `cron:new` → frequency buttons → (hour select / dow→hour select /
direct modal for hourly / raw-cron modal for custom) → create modal (Name
optional, Prompt required) → `run_cron_create` → `create_schedule(email, name,
cron, prompt)` → ephemeral ✅ confirmation rendered via `describe_cron`.

**Manage:** `cron:list` → ephemeral schedules select (≤25) → select →
per-schedule menu (cron, name, on/off, last-run status) → Run now / Pause·Resume
(refresh menu) / Delete (confirm → delete).

Intermediate create steps use `UPDATE_MESSAGE` (type 7) to edit the same ephemeral
message in place; the final timing step returns a `MODAL` (type 9). All responses
are ephemeral (`flags=64`) — the per-user privacy requirement.

### 5.5 Identity, timezone, error handling

- Discord user → email via the existing `_discord_user_email_map`. Unmapped user
  → existing friendly "ask an admin to link your account" message. API calls use
  the end-user path (`X-User-Email`), so schedules are owned by that user.
- Timezone defaults to `Asia/Manila`; no picker in v1.
- Every tasks-client call is wrapped in try/except routed through the existing
  `_friendly_schedule_error` (invalid cron, min-interval 5 min, quota/max,
  not-found / not-owner, 5xx). Empty select values are a no-op
  (`DEFERRED_UPDATE_MESSAGE`). Malformed custom_ids are logged and ignored,
  matching app-builder behavior.

## 6. Testing strategy (TDD)

Write failing tests first, then implement:

1. **Pure unit tests** (`test_cronjob_panel.py`):
   - `cron_from_choice` for every (freq, hour, dow) combination.
   - `encode_cron`/`decode_cron` round-trip (incl. ranges like `1-5`).
   - `describe_cron` for representative expressions.
   - Each component-builder output shape (action rows, button styles, select
     options, modal field ids), including the ≤25 schedules cap.
   - custom_id predicates/extractors for valid and malformed inputs.
2. **Routing tests** (`test_cronjob_routing.py`):
   - Each `cron:*` component custom_id → the correct branch / response type
     (UPDATE vs MODAL vs deferred).
   - Modal submit (`cron:create:*`, `cron:customcron`) → `create_schedule`
     called with the decoded cron + extracted name/prompt.
   - Per-schedule actions → the correct tasks-client method
     (`run_now_schedule` / `enable_schedule` / `disable_schedule` /
     `delete_schedule`).
   - Pause/resume **re-fetches** the schedule and re-renders the menu so the
     button flips Pause↔Resume and `enabled`/last-run reflect the post-action
     state (not a cached toggle).
   - `run_cron_create` rejects a blank/whitespace-only prompt before calling the
     API.

Follows the existing app-builder `pytest.ini` and test conventions.

## 7. Deployment

VPS-in-place, matching the app-builder rollout:
1. Implement + run the test suite inside the `webhook-handler` container.
2. `docker cp` changed files into the running container, `docker restart
   webhook-handler`.
3. Run `setup_cronjob_channel.py` once to post + pin the panel to channel
   `1508420480283967509`.
4. Manual click-through (create daily, create custom, list, run-now,
   pause/resume, delete) to verify.
5. Commit on `feat/gdrive-gmail-connectors` (no AI co-author attribution).

## 8. Risks / open questions

- **Multi-step ephemeral state** is carried in custom_ids (no server-side
  session). Cron expressions and UUIDs are short, so the 100-char custom_id limit
  is not a concern; tests assert the longest custom_ids stay under the limit.
- **`UPDATE_MESSAGE` vs new ephemeral**: editing the same ephemeral message in
  place keeps the flow tidy; if a step needs a brand-new ephemeral, fall back to a
  deferred + `edit_original`.
- **`cronjob` already registered** as a slash subcommand — the panel is reached
  via the channel message, so no command-registration change is required. The
  text command remains a fallback.
- **Result delivery** remains the most likely follow-up to make scheduled runs
  visibly useful.
