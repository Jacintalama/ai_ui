# App Builder Versions + AutoFix + Pre-build Questions - Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Ship the three approved features from `docs/superpowers/specs/2026-07-14-appbuilder-versions-autofix-questions-design.md`: (1) expose the EXISTING git version+rollback system to bot owners with Discord/Slack controls, (2) a narrow AutoFix loop backed by a real browser smoke, (3) pre-build clarifying questions with buttons.

**REVISION v2 (2026-07-14):** the versions feature was re-scoped after discovering a git-backed version+rollback already exists (`routes_projects.py` + preview.html). We REUSE it instead of building a parallel snapshot system. The old Tasks 1-4 (a new `.versions/` snapshot module) were reverted.

**Architecture:** Backend in the tasks service; surfaces reuse existing Discord/Slack panel + `TasksClient` patterns. The git versions/rollback core is shared between the existing `/api/projects/*` routes and new owner-scoped `/api/aiuibuilder/*` routes.

**Tech Stack:** FastAPI/SQLAlchemy async, git (already the version backend), Playwright (in the tasks image), pytest, Discord/Slack block builders.

## Global Constraints

- NO em-dashes or en-dashes anywhere (comments, strings, docs); escape forms only when needed at runtime. This is a hard gate - scan before every commit.
- NO AI attribution in commits. Branch: `feat/appbuilder-versions-autofix-questions` (already cut from main at f233bb4ba).
- NEVER touch `.env`; NEVER deploy local `mcp-servers/tasks/templates.py`.
- tasks tests from `mcp-servers/tasks/` with `--ignore=tests/test_scheduler.py`; webhook tests per-file from `webhook-handler/`.
- Read-tool hook may truncate reads to one line: use Grep -A/-B or `sed -n 'X,Yp'` via bash.
- REUSE, do not duplicate: the git versions/rollback logic in `routes_projects.py` (`GET /{slug}/versions`, `POST /{slug}/rollback`); the publish route's owner auth (`current_user` + `_require_owner`/`_require_role owner`); the enhance route's advisory xact lock (`pg_advisory_xact_lock(hashtext("build:<slug>"))`) and `_LIVE_ENHANCE_STATES`; the Jul-13 paused-build answer flow; My-apps menus; the video-list dispatch/runner patterns.
- The spec (path above) is the requirements source; every implementer must read the relevant section.

---

### Task 1: Owner-scoped git versions + rollback (tasks service) + client

**Files:** Modify `mcp-servers/tasks/routes_projects.py` (extract shared core), `mcp-servers/tasks/routes_aiuibuilder.py` (new owner-scoped routes), `webhook-handler/clients/tasks.py`. Create `mcp-servers/tasks/tests/test_app_git_versions.py`; extend `webhook-handler/tests/test_tasks_client.py`.

**Interfaces:**
- Extract from `routes_projects.py` the version-listing and rollback logic into reusable async functions callable without the web auth wrapper - e.g. `list_app_versions_core(slug) -> list[dict]` and `rollback_app_core(slug, sha) -> dict` (return whatever the existing rollback returns). Do it as an in-place extraction (module-level functions in routes_projects.py) OR a new `app_git_versions.py`; the existing `/api/projects/{slug}/versions` and `/rollback` handlers must then call these and behave BYTE-IDENTICALLY (same responses, same auth, same 400/404/409). Confirm by keeping their existing tests green unchanged.
- New routes on the aiuibuilder router, owner-scoped exactly like `publish_built_app` (`user: CurrentUser = Depends(current_user)`, `_require_owner`/`_require_role(..., "owner", is_admin=False)`, `_validate_slug` fast-fail):
  - `GET /{slug}/versions` -> the same list shape the projects versions route returns.
  - `POST /{slug}/rollback` body `{"sha": str}` -> inside one `async with session()` transaction: `_require_owner`, take `pg_advisory_xact_lock(hashtext(:k))` with `k=f"build:{slug}"`, reject 409 if a task for the slug is in `_LIVE_ENHANCE_STATES`, then call `rollback_app_core(slug, sha)` (holding the lock across it), return its result. Map the core's not-found SHA to 404 and its dirty-tree conflict to 409, mirroring the projects route's own mappings.
- `TasksClient.list_app_versions(user_email, slug)` -> GET `/api/aiuibuilder/{slug}/versions`; `rollback_app(user_email, slug, sha)` -> POST `/api/aiuibuilder/{slug}/rollback` json `{"sha": sha}`. Mirror `publish_app`/`enhance_app` method style (X-User-Email only).

**Steps:** TDD. Route-shape tests (registered, methods, owner dep) like `tests/test_routes_video_shape.py`; if `tests/test_routes_projects.py` has DB-gated behavior tests for versions/rollback, add parallel ones for the aiuibuilder routes following that pattern; else keep to shape + a pure test of the extracted core against a temp git repo if feasible. Client tests extend `test_tasks_client.py` (mirror `publish_app`'s test). Gate: `cd mcp-servers/tasks && python -m pytest tests/test_app_git_versions.py tests/test_routes_projects.py -q`; `cd webhook-handler && python -m pytest tests/test_tasks_client.py -q`. The existing projects-route tests MUST stay green (proves no behavior change). Commit `feat(appbuilder): owner-scoped git versions + rollback API and client`.

---

### Task 2: Versions/rollback buttons on Discord + Slack

**Files:** Modify `webhook-handler/handlers/app_builder_panel.py`, `webhook-handler/handlers/discord_commands.py`, `webhook-handler/handlers/commands.py`, `webhook-handler/handlers/slack_app_builder_panel.py`, `webhook-handler/handlers/slack_interactions.py`. Create `webhook-handler/tests/test_app_versions_surfaces.py`.

**Interfaces:**
- Discord constants: `VERSIONS_PREFIX = "aiuibuild:versions:"`, `VERPICK_PREFIX = "aiuibuild:verpick:"` (select, value = short SHA), confirm `ROLLBACK_OK_PREFIX = "aiuibuild:rbok:"` (custom_id `aiuibuild:rbok:<slug>:<sha>`) / `ROLLBACK_NO_PREFIX = "aiuibuild:rbno:"`. "Versions" button joins `build_project_menu_components` (chunking absorbs it). Flow: Versions click -> `run_app_versions(ctx, slug)` fetches the list and posts a select of recent versions (newest first, current one labeled, skip a rollback option for current); picking a SHA -> a confirm card; confirm -> `run_app_rollback(ctx, slug, sha)` -> `tasks_client.rollback_app` -> respond result + suggest the preview link; 409 -> clean "a build is still running, try again when it finishes".
- Slack: "Versions" button per app row in `build_apps_list_blocks` -> `_do_app_versions` DMs a list where each non-current version row has a Rollback button (`aiuibuild:rollback:<slug>:<sha>`) with a native confirm dialog; `_do_app_rollback` performs it. Mirror `_do_walkthrough_video`'s structure (background spawn, `_bail_if_not_linked`, tasks client, DM result).
- Both consume Task 1's client methods.

**Steps:** TDD with established fixtures (`test_video_runners.py` helpers for Discord; `test_slack_video_interactions.py` for Slack). Cover: menu/row has the Versions button; versions flow posts the select/list; rollback calls the client with (email, slug, sha); 409 conflict message is clean; current version has no rollback control. Gate: the new test file + the touched files' existing suites green. Commit `feat(appbuilder): versions and rollback on Discord and Slack`.

---

### Task 3: AutoFix loop (smoke + narrow fix passes)

**Files:** Create `mcp-servers/tasks/app_smoke.py`, `mcp-servers/tasks/tests/test_app_smoke.py`, `mcp-servers/tasks/tests/test_autofix_loop.py`. Modify `mcp-servers/tasks/claude_executor.py`, `mcp-servers/tasks/routes_execution.py`.

**Interfaces:**
- `app_smoke.smoke_app(slug, *, timeout_ms=15000) -> str | None`: load the app's INTERNAL preview URL (grep how the tasks service serves `preview-app/<slug>/` and hit it on `http://localhost:8210/...` the way `video_capture` hits localhost) with headless Playwright chromium (same launch args as `video_capture.py`), wait 2500ms, collect non-200 main response / `pageerror` / `console.error` / failed requests, return a deduped report string (max ~10 lines, each `- <source>: <message>`) or None when clean. ALL internal exceptions -> return None (fail open) with a logged warning.
- `claude_executor.build_autofix_prompt(*, slug, errors) -> str`: fix ONLY the listed errors, smallest change, no redesign/refactor/restyle; same completion-sentinel contract as `build_verify_prompt`.
- `routes_execution`: module-level seam `_smoke_app = app_smoke.smoke_app` (call the module global so tests monkeypatch it, like the scheduler-video seams). Loop inserted in `_run_execution` right after the `outcome.kind == "completed" and slug` point, BEFORE the existing verify block: up to `AUTOFIX_MAX_PASSES = 2` iterations of smoke -> if report, append `--- AUTOFIX n/2 ---` + report to the execution log, run `_stream_claude(build_autofix_prompt(...))`, re-smoke. If a report remains after the loop, append it to the task result so the user-facing failure shows concrete errors; do NOT otherwise change the completed/verify control flow.
- Tests: smoke module with a fake page object (like `_FakeWalkPage`); loop by monkeypatching `_smoke_app` + `_stream_claude` (clean -> zero fix calls; one transient error -> exactly one fix call; persistent -> exactly two then proceed, result contains the report); prompt content asserts "ONLY these errors" + no-redesign phrasing.

**Steps:** TDD. Gate: `cd mcp-servers/tasks && python -m pytest tests/test_app_smoke.py tests/test_autofix_loop.py tests/test_video_capture.py -q`. Commit `feat(appbuilder): real-browser smoke + narrow autofix loop`.

---

### Task 4: Pre-build questions backend

**Files:** Create `mcp-servers/tasks/migrations/031_task_questions.sql`, `mcp-servers/tasks/tests/test_prebuild_questions.py`. Modify `mcp-servers/tasks/claude_executor.py`, `mcp-servers/tasks/models.py`, `mcp-servers/tasks/routes_aiuibuilder.py`, `mcp-servers/tasks/routes_execution.py`, `mcp-servers/tasks/scheduler.py`, `webhook-handler/clients/tasks.py`.

**Interfaces:**
- Migration 031 (idempotent like 030; confirm the task table name from `models.py` TaskItem `__tablename__` first): `ADD COLUMN IF NOT EXISTS questions_json JSONB;` and `ADD COLUMN IF NOT EXISTS questions_asked_at TIMESTAMPTZ;`.
- `claude_executor.build_prebuild_questions_prompt(description) -> str`: reply exactly `NO_QUESTIONS` when clear, else ONLY JSON `{"questions": [{"q": str, "options": [str, ...]}]}` (2-4 options each, max 3 questions, q under 100 chars). `parse_prebuild_questions(text) -> list[dict] | None`: None for NO_QUESTIONS/garbage/empty; trims over-cap to 3.
- Build flow: in the aiuibuilder `/build` route for NON-template builds (template_key falsy), before dispatching the normal pipeline, run the question pass via the same one-shot claude mechanism `clarify` uses (grep it). Questions found -> task status `awaiting_input`, store `questions_json` + `questions_asked_at`, DO NOT start the build. `BuildStatusResponse` gains `questions: list | None` (from `questions_json`).
- Answer: extend `POST /build/{task_id}/answer` request model with optional `answers: list[str] | None`; when present, append `\n\nUser choices:\n- <q> -> <answer>` lines to the description, clear `questions_json`, resume via the existing free-text resume path. `answers == []` or literal `"__skip__"` -> resume unchanged plus "User skipped the questions; use sensible defaults."
- Timeout sweep: factor a pure helper `questions_timed_out(asked_at, now, *, minutes=10) -> bool` (unit-tested); call it in the scheduler tick to auto-skip `awaiting_input` tasks WITH `questions_json` older than 10 min. Never touches Jul-13 mid-build questions (those have `questions_json` NULL).
- `TasksClient.answer_build(...)`: extend with `answers: list[str] | None = None` (read current signature; keep back-compat).

**Steps:** TDD: prompt/parse pure tests (NO_QUESTIONS, valid, garbage, 5-question trims to 3); answer-model shape; `questions_timed_out` helper. Regression: `tests/test_schedule_kind.py`, aiuibuilder route tests, the Jul-13 answer tests stay green. Gate accordingly. Commit `feat(appbuilder): pre-build clarifying questions backend`.

---

### Task 5: Questions on web, Discord, Slack

**Files:** Modify the web build form (grep for the build POST - likely `mcp-servers/tasks/static/projects.html` or `video.html`'s sibling; find it), `webhook-handler/handlers/app_builder_panel.py`, `webhook-handler/handlers/discord_commands.py`, `webhook-handler/handlers/commands.py`, `webhook-handler/handlers/slack_app_builder_panel.py`, `webhook-handler/handlers/slack_interactions.py`. Create `webhook-handler/tests/test_prebuild_questions_surfaces.py`.

**Interfaces:**
- Each surface already reports build progress and the Jul-13 free-text question; EXTEND those paths: when `questions` is present, render each question with option buttons + a "Just build it" skip.
- Discord: option custom_id `aiuibuild:qopt:<task_id>:<qi>:<oi>`, skip `aiuibuild:qskip:<task_id>`. Selecting accumulates into a per-task pending-answers dict on the handler (like `_pending_schedules`); when all answered (or skip) -> call the extended `answer_build` with ordered answers -> confirm in-thread.
- Slack: same semantics with block buttons in the DM; action_ids mirror Discord.
- Web: the build form status area renders question cards with option buttons; clicking posts to the answer endpoint with `answers`; skip sends `__skip__`.
- Consumes Task 4's shapes exactly. Mid-build free-text questions (questions=None, question=str) still render the Jul-13 way.

**Steps:** TDD on builders + handlers with established fixtures. Cover: buttons render per question, partial answers accumulate, full answers call client once with ordered answers, skip works, Jul-13 free-text path unchanged. Commit `feat(appbuilder): pre-build questions on web, Discord, Slack`.

---

### Task 6: Final review + suites

Dash-scan the branch diff additions (U+2013/U+2014 -> zero). Full sweeps: tasks feature files + regression `tests/ -q --ignore=tests/test_scheduler.py -k "aiuibuilder or projects or schedule or video or smoke or autofix or questions"`; webhook feature + regression. Dispatch a whole-branch review (most capable model) against the spec with the review-package script; fix Critical/Important; merge to main and push after clean.

### Task 7: Deploy + live verification

Tar-push changed files (orchestrator rsync is broken on this box), rebuild `tasks` + `webhook-handler`, migration check (`\d tasks.<task table>` shows questions_json). Live verify: (1) blank build from Discord -> questions appear with buttons -> answer -> build completes; (2) Versions button on that app lists git versions -> rollback to a prior one works and the preview reflects it; (3) an execution log shows the `--- AUTOFIX` section on a build with an injected error, or confirm smoke runs clean on a normal build. healthz green. Update memory sync state.
