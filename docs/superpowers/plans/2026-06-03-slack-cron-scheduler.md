# Slack Cron Scheduler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bring the cron scheduler to Slack — a `#cron-job` panel, plain-English create form, per-user dashboard, and per-schedule actions — with each run's result delivered to the user's Slack DM, by adding a platform-aware delivery seam to the shared backend and a Slack UX layer that mirrors Discord's.

**Architecture:** `tasks.schedules` gains a `delivery_platform` column (default `discord`). `scheduler.py` delivery is generalized to pass `platform`; the webhook-handler `/internal/schedule-result` endpoint branches to post into a Slack DM when `platform="slack"`. A new Slack UX layer (panel/dashboard/modal/card builders + interaction routing) creates schedules with `delivery_platform="slack"` and `delivery_channel_id=<user DM channel>`. Schedule CRUD, the cron tick, execution, and the entire Discord flow are unchanged.

**Tech Stack:** Python, FastAPI + SQLAlchemy + asyncpg (tasks), pytest, Slack Block Kit / Web API.

**Spec:** `docs/superpowers/specs/2026-06-03-slack-cron-scheduler-design.md`

**Reuse (no change):** `schedule_parse.parse_when(text) -> (cron, human) | None`; tasks-client schedule methods (`list_schedules`, `create_schedule`, `delete_schedule`, `pause_schedule`→/disable, `resume_schedule`→/enable, `run_schedule_now`→/run-now, `update_schedule`); the cron tick + execution; the `aiuisched:*` id strings. Discord builders to MIRROR (read them): `build_schedules_panel`, `build_schedules_dashboard`, `build_schedule_card`, `build_schedule_modal`, `build_schedule_edit_modal`, `build_retry_components` in `webhook-handler/handlers/app_builder_panel.py` (~430-745).

**Local-test note:** tasks-service DB tests can't run locally (no DB; fixtures TRUNCATE). For Task 1 verify imports/migration-collection; webhook-handler tasks (2-5) run fully locally.

---

## Task 1: Backend — `delivery_platform` column + scheduler generalization

**Files:** new `mcp-servers/tasks/migrations/018_schedule_delivery_platform.sql`; modify `models.py` (Schedule ~113-138), `routes_schedules.py` (`CreateScheduleIn` ~61, create route ~78-117), `scheduler.py` (~173-214); test `mcp-servers/tasks/tests/`.

- [ ] **Step 1: Write tests** (DB-backed → for CI): creating a schedule with `delivery_platform="slack"` persists it; default is `"discord"` when omitted. Mirror an existing `routes_schedules` create test.
- [ ] **Step 2: Verify locally** what's runnable: module imports, migration file collects, route registers (DB tests error on ConnectionRefused — expected).
- [ ] **Step 3: Implement**
  - `migrations/018_schedule_delivery_platform.sql`:
    ```sql
    -- Idempotent: re-applied on every startup. Existing rows default to 'discord'
    -- so all current Discord behavior is preserved.
    ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS delivery_platform text DEFAULT 'discord';
    ```
  - `models.py` Schedule: `delivery_platform = Column(Text, nullable=False, server_default="discord")` (next to `delivery_channel_id`).
  - `routes_schedules.py` `CreateScheduleIn`: add `delivery_platform: str = "discord"`; on insert, set `delivery_platform=body.delivery_platform`.
  - `scheduler.py`: rename `_deliver_to_discord` → `_deliver_result` and add a `platform: str` param; include `"platform": platform` in the POST json. In `_finalize_run`, read `platform = getattr(sched, "delivery_platform", "discord") or "discord"` and call `_deliver_result(delivery_channel, platform, sched.name, status, result, str(sched.id))`.
- [ ] **Step 4: Re-verify** imports + route registration; report DB-test baseline.
- [ ] **Step 5: Commit** `feat(tasks): delivery_platform on schedules + platform-aware delivery seam`

---

## Task 2: webhook-handler — platform-aware `/internal/schedule-result` + client param

**Files:** modify `webhook-handler/main.py` (`ScheduleResultIn` ~552, endpoint ~568-590), `webhook-handler/clients/tasks.py` (`create_schedule` ~81-93); test `webhook-handler/tests/`.

- [ ] **Step 1: Write failing tests**
  - Endpoint: a `platform="slack"` body → calls `slack_client.post_message(channel_id, text=…)` (mock both clients; use a TestClient or call the handler). Discord/absent platform → `discord_client.post_channel_message` (unchanged). Slack path does NOT 503 when `discord_client is None` (gate Slack on `slack_client`).
  - Client: `create_schedule(..., delivery_platform="slack")` includes `delivery_platform` in the POST body (respx, mirror existing create_schedule test).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - `ScheduleResultIn`: add `platform: str = "discord"`.
  - Endpoint: after the secret check, branch BEFORE the `discord_client is None` guard:
    ```python
    if body.platform == "slack":
        if slack_client is None:
            raise HTTPException(status_code=503, detail="Slack not configured")
        text = _format_schedule_result(body.schedule_name, body.status, body.result)
        blocks = None
        if body.schedule_id and body.status not in ("completed", "skipped"):
            from handlers.slack_schedule_panel import build_retry_blocks
            blocks = build_retry_blocks(body.schedule_id)
        await slack_client.post_message(channel=body.channel_id, text=text, blocks=blocks)
        return {"ok": True}
    # --- existing Discord path below (discord_client guard + post_channel_message) ---
    ```
    (`_format_schedule_result` is plain text and works for Slack mrkdwn fallback; reuse it.)
  - `clients/tasks.py` `create_schedule`: add `delivery_platform: str = "discord"` param; `if delivery_platform: body["delivery_platform"] = delivery_platform`.
- [ ] **Step 4: Run, verify pass; full suite green.**
- [ ] **Step 5: Commit** `feat(webhook): Slack delivery branch in /internal/schedule-result + create_schedule platform param`

> NOTE: `build_retry_blocks` is created in Task 3 — if implementing Task 2 first, stub the import behind the `if body.schedule_id` branch or land Task 3's builder first. Recommended order: Task 3 before Task 2's endpoint, OR define `build_retry_blocks` in Task 3 and keep Task 2's import local (lazy) so tests for the happy path (completed status → no retry) pass independently.

---

## Task 3: Slack schedule builders (new `handlers/slack_schedule_panel.py`)

**Files:** create `webhook-handler/handlers/slack_schedule_panel.py`; test `webhook-handler/tests/test_slack_schedule_panel.py`.

Mirror the Discord builders (`app_builder_panel.py` schedule section) in Block Kit. Reuse the `aiuisched:*` id strings (import from `app_builder_panel` or redefine identical constants — prefer importing to stay DRY).

- [ ] **Step 1: Write failing tests** — for each builder, assert the key shape:
  - `build_schedules_panel()` → blocks with an actions block containing a button action_id `SCHED_OPEN_ID` ("⏰ Open my schedules").
  - `build_schedules_dashboard(schedules)` → a "New schedule" button (`SCHED_NEW_ID`) + one row/section per schedule; empty list → "no schedules yet" text.
  - `build_schedule_card(sched)` → Run(`SCHED_RUN_PREFIX+id`)/Pause or Resume/Edit/Delete buttons.
  - `build_schedule_modal()` → a `view` dict (callback_id `SCHED_MODAL_ID`) with two `plain_text_input` blocks: "what" + "when".
  - `build_schedule_edit_modal(sched)` → pre-filled edit `view` (callback_id `SCHED_EDITMODAL_PREFIX+id`).
  - `build_retry_blocks(schedule_id)` → a Block Kit actions block with a "Retry" button (`SCHED_RUN_PREFIX+id`).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the builders (Block Kit; use the existing Slack `_button`/`_link_button` style from `slack_app_builder_panel.py`, or local helpers). Pause vs Resume button depends on `sched["enabled"]`. Keep ≤5 elements per actions block.
- [ ] **Step 4: Run, verify pass; full suite green.**
- [ ] **Step 5: Commit** `feat(slack): schedule panel/dashboard/card/modal Block Kit builders`

---

## Task 4: Slack interactions — route `aiuisched:*` + modal submits

**Files:** modify `webhook-handler/handlers/slack_interactions.py`; test `webhook-handler/tests/test_slack_schedule_interactions.py`.

- [ ] **Step 1: Write failing tests**
  - `aiuisched:open` block_action → resolves email (`_bail_if_not_linked`), `open_dm`, posts `build_schedules_dashboard(list_schedules(email))` to the DM (ephemeral fallback if no DM).
  - `aiuisched:new` → `open_modal(trigger_id, build_schedule_modal())`.
  - schedule `view_submission` (callback_id `SCHED_MODAL_ID`) → reads what+when, `parse_when(when)` → `create_schedule(email, name, cron, prompt, delivery_channel_id=<dm>, delivery_platform="slack")`, posts confirmation to DM; `parse_when` None → friendly error.
  - `aiuisched:run|pause|resume|del:<id>` → calls the matching tasks-client method + re-renders/acks.
  - edit `view_submission` (`SCHED_EDITMODAL_PREFIX`) → `update_schedule`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - In `_handle_block_actions`: add `aiuisched:*` routing (mirror the App Builder branches; background-task tracked via `router._background_tasks`). For open: `email = await self._bail_if_not_linked(user_id)`; `dm = await self.slack.open_dm(user_id)`; post dashboard (or ephemeral fallback). For run/pause/resume/del: resolve email, call `self.router._tasks_client.<method>(email, id)`, then re-post the dashboard (or a status line).
  - In `_handle_view_submission`: branch on the schedule callback_ids (alongside the App Builder one). Create: resolve email, `parse_when`, `open_dm`, `create_schedule(... delivery_platform="slack", delivery_channel_id=dm)`, DM a "✅ Scheduled" confirmation. Edit: `update_schedule`.
  - Add `is_*`/`slug-from`-style helpers or inline prefix checks consistent with the file's style.
- [ ] **Step 4: Run, verify pass; full suite green.**
- [ ] **Step 5: Commit** `feat(slack): schedule interactions (open/new/create/list/actions/edit)`

---

## Task 5: Pin the panel in #cron-job + full regression + review

**Files:** (optional) `scripts/setup_slack_cron_channel.py` or a one-off post; tests.

- [ ] **Step 1: Full suites** — `cd webhook-handler && python -m pytest -q` (all green); tasks-service tests for CI.
- [ ] **Step 2: Final code review** across the whole diff (focus: platform default preserves Discord, Slack delivery gate order, parse_when failure handling, ≤5 elements/block, email-not-linked path).
- [ ] **Step 3: Pin step (deploy-time, documented):** post `build_schedules_panel()` to `#cron-job` (`C0B8TK8MYHW`) via `chat.postMessage` + `pins.add` (bot has chat:write + pins:write). This is a one-off run, not committed code (or a small idempotent script). Document in deploy notes.
- [ ] **Step 4: Commit** any test fixups.

---

## Deploy notes (after merge, on approval)
- Deploy `tasks` (restart → migration 018 auto-applies `delivery_platform`; generalized delivery) AND `webhook-handler` (main.py, clients/tasks.py, new slack_schedule_panel.py, slack_interactions.py).
- Diff each file vs the live container first (container-vs-repo drift has bitten before — e.g. routes_discord_links).
- Post + pin the `#cron-job` scheduler panel (Slack) after deploy.
- Merge to `main` so a redeploy keeps it.
- `WEBHOOK_HANDLER_URL` + `INTERNAL_CALLBACK_SECRET` must be set in the tasks container (already are — Discord delivery uses them).

## Risks
- Default `delivery_platform='discord'` everywhere keeps existing Discord schedules byte-for-byte unchanged. Enforce in tests.
- The Slack delivery branch must precede the `discord_client is None` 503 guard.
- DM channel id stored at create time is durable — no per-run `open_dm` needed.
