# Scheduler Platform-Scoping + Output Polish (Ship 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Slack cron shows/runs only Slack schedules (deliver to Slack DM), Discord only Discord; show human time on the Slack card; make the scheduled-task result message + agent output clean & minimal.

**Architecture:** Add `delivery_platform` to the schedule list output + a `platform` filter on `GET /schedules`; the bots pass their platform when listing. Render `cron_to_human` on the Slack card. Restyle `_format_schedule_result` (clean & quiet) and tighten the existing agent OUTPUT STYLE directive.

**Tech Stack:** Python, FastAPI/SQLAlchemy (tasks), pytest, Slack Block Kit / Discord.

**Spec:** `docs/superpowers/specs/2026-06-03-scheduler-platform-scope-and-polish-design.md`

**Local-test note:** tasks-service DB tests can't run locally (no DB) — verify imports/route for Task 1; the create-route tests there are mock-based and DO run. webhook-handler tasks run fully locally.

---

## Task 1: tasks — `delivery_platform` in list output + `platform` filter on GET /schedules

**Files:** Modify `mcp-servers/tasks/routes_schedules.py` (`_serialize` ~236; GET handler ~64). Test in `mcp-servers/tasks/tests/`.

- [ ] **Step 1: Tests** (mock-based, like existing routes_schedules tests): list output dict includes `delivery_platform`; `GET /schedules?platform=slack` returns only slack rows; no param returns all.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - `_serialize`: add `"delivery_platform": s.delivery_platform` to the returned dict.
  - GET handler: add `platform: str = Query(default="")` (import `Query` from fastapi); after `stmt = select(Schedule).where(Schedule.user_email == ...)`, add `if platform: stmt = stmt.where(Schedule.delivery_platform == platform)`.
- [ ] **Step 4: Run, verify pass** (+ imports/route registration).
- [ ] **Step 5: Commit** `feat(tasks): expose delivery_platform + platform filter on GET /schedules`

---

## Task 2: webhook-handler client — `list_schedules(platform=)`

**Files:** Modify `webhook-handler/clients/tasks.py` (`list_schedules` ~78). Test `webhook-handler/tests/` (respx).

- [ ] **Step 1: Test** — `list_schedules(email, platform="slack")` issues `GET /schedules?platform=slack`; no platform → no query param (or omitted).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — add `platform: str | None = None`; build `params={"platform": platform}` only when set; pass to the GET. Keep return shape.
- [ ] **Step 4: Run, verify pass; full suite.**
- [ ] **Step 5: Commit** `feat(webhook): list_schedules platform filter`

---

## Task 3: Platform-scope the bots + human time on Slack card

**Files:** Modify `webhook-handler/handlers/slack_interactions.py` (lines **224**, **304**), `webhook-handler/handlers/commands.py` (the **7** sites: **1309, 1683, 1811, 1830, 1842, 1917, 1933**), `webhook-handler/handlers/slack_schedule_panel.py` (`build_schedule_card`, and `build_schedules_dashboard` if it shows cron). Tests: `tests/test_slack_schedule_*` + Discord cron tests.

- [ ] **Step 1: Tests**
  - Slack: opening the dashboard calls `list_schedules(email, platform="slack")`; `build_schedule_card` renders the human time (`cron_to_human`) — assert "every day at 9:41 PM"-style text present, raw `41 21 * * *` NOT present.
  - Discord: `run_cron_list` and `_cron_menu_for` call `list_schedules(..., platform="discord")` (and a Slack-platform schedule is filtered out). Mirror existing Discord schedule tests.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - Slack `slack_interactions.py`: at both `list_schedules(email)` calls (224, 304) → `list_schedules(email, platform="slack")`.
  - Discord `commands.py`: ALL 7 `list_schedules(email)` calls → add `platform="discord"`. (Don't touch Discord create — it correctly defaults to discord.)
  - `slack_schedule_panel.py`: `from handlers.schedule_format import cron_to_human`; in `build_schedule_card`, replace the raw `` `{cron}` `` with `cron_to_human(cron)` (e.g. "every day at 9:41 PM"). Do the same in `build_schedules_dashboard` if it prints the cron.
- [ ] **Step 4: Run, verify pass; full suite.**
- [ ] **Step 5: Commit** `feat(scheduler): platform-scope Slack/Discord schedule lists + human time on Slack card`

---

## Task 4: Minimalist result output + tighten agent directive

**Files:** Modify `webhook-handler/main.py` (`_format_schedule_result` ~561); `mcp-servers/tasks/scheduler.py` (existing OUTPUT STYLE directive ~159). Tests: `webhook-handler/tests/` for the formatter.

- [ ] **Step 1: Tests** (formatter):
  - Discord-style name `"every day at 9:41 PM: give me the best quote"` + status completed → output has `**give me the best quote**`, the body, and a `_every day at 9:41 PM_` footer; NO `✅`.
  - Slack-style bare name `"give me the best quote"` (no `": "`) → title = the name, body present, NO footer, NO `✅`.
  - status `failed` → output starts with `⚠️`.
  - very long body → result ≤ 1990 chars.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - `_format_schedule_result(name, status, result)`: split `name` on the first `": "` → `(when, title)` if present, else `title=name, when=None`. completed → `f"**{title}**\n\n{body}"` + (`f"\n\n_{when}_"` if when). non-completed → `f"⚠️ **{title}** — {status}\n\n{body}"`. Truncate to 1990. Never raise (guard the split).
  - `scheduler.py` line ~159: EDIT the existing OUTPUT STYLE sentence in place — keep "delivered inside a branded card; no ASCII boxes/banners" and fold in "format minimally: a short bold title, then the content, then at most one brief line of context; minimal emoji." Do NOT append a second directive.
- [ ] **Step 4: Run, verify pass; full suite.**
- [ ] **Step 5: Commit** `feat(scheduler): clean & quiet result message + minimal agent output directive`

---

## Task 5: Full regression + final review
- [ ] `cd webhook-handler && python -m pytest -q` green; tasks-service tests for CI.
- [ ] Final code review across the diff (focus: all 7 Discord sites filtered; Slack DM delivery for run-now of a slack schedule; formatter never raises; directive edited not duplicated).

## Deploy notes (after merge, on approval)
- Deploy `tasks` (routes_schedules, scheduler) + `webhook-handler` (main.py, clients/tasks.py, slack_interactions.py, slack_schedule_panel.py, commands.py). **Diff each file vs the live container first** — scheduler.py has uncommitted connector code on prod (reconcile like before); commands.py may have drift. **Use `docker cp` + restart** (not compose up, which reverts cp'd code) and re-commit the image after.
- Merge to main.

## Risks
- The big one: `scheduler.py` on prod has uncommitted `_connector_access_note` code — reconcile (container base + this change) before deploying, exactly as the prior scheduler deploy did.
- Default `platform` omitted = all (any un-updated caller keeps working; only the 7 Discord + 2 Slack sites are scoped).
