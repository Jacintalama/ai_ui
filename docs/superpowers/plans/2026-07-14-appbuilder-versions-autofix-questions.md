# App Builder Versions + AutoFix + Pre-build Questions - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the three approved features from `docs/superpowers/specs/2026-07-14-appbuilder-versions-autofix-questions-design.md`: app version timeline with non-destructive restore, a narrow AutoFix loop backed by a real browser smoke, and pre-build clarifying questions with buttons.

**Architecture:** All backend work lands in the tasks service (new `app_versions.py` + `app_smoke.py` modules, hooks in `routes_execution._run_execution`, routes in `routes_aiuibuilder.py`, prompts in `claude_executor.py`). Surfaces reuse existing patterns: web `preview.html` panel, Discord `app_builder_panel.py` + `discord_commands.py`, Slack `slack_app_builder_panel.py` + `slack_interactions.py`, `TasksClient` methods.

**Tech Stack:** FastAPI/SQLAlchemy async + raw SQL migrations, Playwright (already in tasks image), pytest, Discord/Slack block builders.

## Global Constraints

- NO em-dashes or en-dashes anywhere; escape forms only when the char is needed at runtime.
- NO AI attribution in commits. Branch: `feat/appbuilder-versions-autofix-questions` from main.
- NEVER touch `.env`; NEVER deploy local `mcp-servers/tasks/templates.py`.
- tasks tests from `mcp-servers/tasks/` with `--ignore=tests/test_scheduler.py`; webhook tests per-file from `webhook-handler/`.
- Read-tool hook may truncate reads to one line: use Grep -A/-B or `sed -n 'X,Yp'` via bash.
- Existing seams to REUSE, not duplicate: paused-build answer flow (`POST /api/aiuibuilder/build/{task_id}/answer`, `BuildStatusResponse.question`, `awaiting_input` status), My-apps menus, `_handle_video_route`-style dispatch patterns.
- The spec (path above) is the requirements source; every task's implementer must read it.

---

### Task 1: Versions core module (tasks service)

**Files:** Create `mcp-servers/tasks/app_versions.py`, `mcp-servers/tasks/tests/test_app_versions.py`.

**Interfaces produced:**
- `EXCLUDE_DIRS = {".versions", ".video", "node_modules", "__pycache__"}`
- `snapshot_app(apps_dir: str, slug: str, *, kind: str, label: str) -> int` - copies the app dir (minus EXCLUDE_DIRS) into `.versions/v<N>/`, appends `{no, created_at (utc iso), kind, label[:80]}` to `.versions/manifest.json`, prunes to the newest `MAX_VERSIONS = 10` (snapshot dirs + manifest entries), returns the new version number. Missing/empty app dir raises `ValueError`.
- `list_versions(apps_dir: str, slug: str) -> list[dict]` - manifest entries newest first; `[]` when none/corrupt.
- `restore_version(apps_dir: str, slug: str, version_no: int) -> int` - snapshots current state first (`kind="restore"`, label `f"before restore to v{version_no}"`), then replaces live app files with the snapshot copy (delete live files except EXCLUDE_DIRS, copy snapshot in), appends nothing extra (the pre-restore snapshot IS the new entry), returns that new version number. Unknown version raises `KeyError`.

**Steps:** TDD. Tests (tmp_path-based, no DB): snapshot creates v1 with manifest entry and copies files but not EXCLUDE_DIRS; second snapshot -> v2; 11 snapshots -> only newest 10 remain and manifest matches dirs; list newest-first; corrupt manifest -> []; restore replaces live content with target version bytes AND creates a new pre-restore snapshot; restore of unknown version raises KeyError; labels truncated to 80. Then implement (pure stdlib: shutil, json, datetime). Run `python -m pytest tests/test_app_versions.py -q`. Commit `feat(appbuilder): version snapshot core`.

---

### Task 2: Versions API + snapshot hook + client

**Files:** Modify `mcp-servers/tasks/routes_aiuibuilder.py`, `mcp-servers/tasks/routes_execution.py`, `webhook-handler/clients/tasks.py`. Create `mcp-servers/tasks/tests/test_app_versions_api.py`; extend `webhook-handler/tests/test_tasks_client.py`.

**Interfaces:**
- Consumes Task 1's module.
- Produces routes on the aiuibuilder router (mirror the auth/ownership pattern of the existing `POST /{slug}/publish` route EXACTLY, including how it resolves the owner and 403s): `GET /{slug}/versions` -> `{"versions": [...]}`; `POST /{slug}/restore` body `{"version_no": int}` -> 409 when the slug has a live build/enhance (reuse the same live-state check the enhance route uses, `_LIVE_ENHANCE_STATES`), 404 unknown version, else `{"versions": [...], "restored_to": n}`.
- Snapshot hook: in `routes_execution._run_execution`, at the point where an app task transitions to `completed` and `slug` is set (the same place the existing verify block keys off `outcome.kind == "completed" and slug`), call `snapshot_app(APPS_DIR, slug, kind=..., label=task.description)` in a try/except that logs but never fails the build. kind: "enhance" when the task is an enhance (the enhance route marks tasks - find the discriminator it sets, e.g. description prefix or a column, and use what exists; if nothing exists, pass "build").
- `TasksClient.list_app_versions(user_email, slug)` -> GET `/api/aiuibuilder/{slug}/versions` (confirm the exact mounted prefix by reading how `publish` is called in the client and mirror it); `restore_app_version(user_email, slug, version_no)` -> POST `.../restore`.

**Steps:** TDD where testable without DB (route registration/shape assertions like `tests/test_routes_video_shape.py`; client tests follow `test_tasks_client.py` fake-request pattern). DB-gated behavior tests only if the repo already has that pattern for aiuibuilder routes (check `tests/test_routes_aiuibuilder.py` and follow it). Regression: the touched files' existing test files stay green. Commit `feat(appbuilder): versions API, snapshot-on-complete, client`.

---

### Task 3: Versions on the web preview panel

**Files:** Modify `mcp-servers/tasks/static/preview.html`.

**Interfaces:** Consumes `GET /api/aiuibuilder/{slug}/versions` + `POST .../restore` with the same auth the page already uses for its other panels (it has existing side panels: graph/versions-of-video/status - find the existing panel pattern and clone it). Adds a "Versions" panel: list (label, kind, relative time), Restore button per row EXCEPT the newest, `confirm()` dialog, on success re-fetch list and reload the preview iframe. Errors render in the panel, never alert-spam.

**Steps:** Follow the file's existing panel JS conventions exactly. No test harness exists for this file: verify with the node parse-check trick used before (`new Function(scriptBody)`) and by grepping that all new fetches use the page's existing auth helper. Commit `feat(appbuilder-ui): versions panel with restore`.

---

### Task 4: Versions buttons on Discord + Slack

**Files:** Modify `webhook-handler/handlers/app_builder_panel.py`, `webhook-handler/handlers/discord_commands.py`, `webhook-handler/handlers/commands.py`, `webhook-handler/handlers/slack_app_builder_panel.py`, `webhook-handler/handlers/slack_interactions.py`. Create `webhook-handler/tests/test_app_versions_surfaces.py`.

**Interfaces:**
- Discord: `VERSIONS_PREFIX = "aiuibuild:versions:"`, `RESTORE_PREFIX = "aiuibuild:restore:"` (custom_id `aiuibuild:restore:<slug>:<no>`), confirm card prefixes `aiuibuild:restok:<slug>:<no>` / `aiuibuild:restno:`. "Versions" button joins `build_project_menu_components` (chunking absorbs it). Flow: Versions click -> `run_app_versions(ctx, slug)` posts the list with restore buttons (max 10 rows of buttons - Discord 5-row limit means chunk into per-message rows like the video list does, or one select of versions + confirm; USE A SELECT (`aiuibuild:verpick:<slug>`, options = versions, value = no) then a confirm card - stays within limits). Confirm -> `run_app_restore(ctx, slug, no)` -> client call, respond result, suggest preview link.
- Slack: "Versions" button per app row -> DM list where each version row has a Restore button with a native confirm dialog (same `_delete_button`-style confirm pattern already in the file). Handlers `_do_app_versions`, `_do_app_restore` mirror `_do_walkthrough_video`'s structure (background spawn, `_bail_if_not_linked`, tasks client, DM results).
- Both consume the Task 2 client methods.

**Steps:** TDD with the established fixture styles (`test_video_runners.py` helpers for Discord runners; `test_slack_video_interactions.py` for Slack). Cover: menu/row contains the button; versions flow posts list; restore calls client with right args; 409 conflict message is clean ("a build is still running"). Commit `feat(appbuilder): versions and restore on Discord and Slack`.

---

### Task 5: AutoFix loop (smoke + narrow fix passes)

**Files:** Create `mcp-servers/tasks/app_smoke.py`, `mcp-servers/tasks/tests/test_app_smoke.py`, `mcp-servers/tasks/tests/test_autofix_loop.py`. Modify `mcp-servers/tasks/claude_executor.py` (new prompt builder), `mcp-servers/tasks/routes_execution.py`.

**Interfaces:**
- `app_smoke.smoke_app(slug: str, *, timeout_ms: int = 15000) -> str | None`: builds the internal preview URL (find how the tasks service serves `preview-app/<slug>/` internally and hit `http://localhost:8210/...` the way the walk capture hits localhost; confirm the exact internal path by grepping routes), loads it with Playwright chromium (mirror `video_capture.py`'s launch args), waits 2500ms, collects page errors / console.error / failed requests / non-200 main response, returns a deduped report string (max ~10 lines, each `- <source>: <message>`) or None when clean. ALL exceptions inside -> return None (fail open) with a logged warning.
- `claude_executor.build_autofix_prompt(*, slug: str, errors: str) -> str`: instructs fixing ONLY the listed errors with the smallest change; forbids redesign/refactor/restyle; ends with the same completion sentinel contract other prompts in the file use (mirror `build_verify_prompt`'s structure).
- `routes_execution`: module-level seams for testability (mirror the scheduler-video pattern): `_smoke_app = app_smoke.smoke_app` and the loop calls the module global so tests can monkeypatch. Loop inserted in `_run_execution` right after `outcome.kind == "completed" and slug` (BEFORE the existing verify block): up to `AUTOFIX_MAX_PASSES = 2` iterations of smoke -> if report, log `--- AUTOFIX n/2 ---` + report to the execution log, run `_stream_claude(build_autofix_prompt(...))`, re-smoke. If a report remains after the loop, append it to the task result so the user-facing failure/verify path shows concrete errors; do NOT change the completed/verify control flow otherwise.
- Tests: smoke module unit-tested with a fake page object (like `_FakeWalkPage`); loop tested by monkeypatching `_smoke_app` + `_stream_claude` (clean -> zero fix calls; one transient error -> exactly one fix call; persistent -> exactly two then proceeds, result contains the report). Prompt content test asserts the "ONLY these errors" and no-redesign phrases.

**Steps:** TDD as above; regression `tests/test_video_capture.py` (shares Playwright patterns) + any existing `routes_execution` tests. Commit `feat(appbuilder): real-browser smoke + narrow autofix loop`.

---

### Task 6: Pre-build questions backend

**Files:** Create `mcp-servers/tasks/migrations/031_task_questions.sql`, `mcp-servers/tasks/tests/test_prebuild_questions.py`. Modify `mcp-servers/tasks/claude_executor.py`, `mcp-servers/tasks/models.py`, `mcp-servers/tasks/routes_aiuibuilder.py`, `mcp-servers/tasks/routes_execution.py`, `mcp-servers/tasks/scheduler.py` (timeout sweep), `webhook-handler/clients/tasks.py`.

**Interfaces:**
- Migration 031 (idempotent like 030): `ALTER TABLE tasks.task_items ADD COLUMN IF NOT EXISTS questions_json JSONB;` plus `ADD COLUMN IF NOT EXISTS questions_asked_at TIMESTAMPTZ;` (confirm the actual task table name from models.py TaskItem `__tablename__` before writing).
- `claude_executor.build_prebuild_questions_prompt(description: str) -> str`: single-completion prompt: reply exactly `NO_QUESTIONS` when clear, else ONLY JSON `{"questions": [{"q": str, "options": [str, ...]}]}` (2-4 options each, max 3 questions, each q under 100 chars). `parse_prebuild_questions(text: str) -> list[dict] | None`: None for NO_QUESTIONS/garbage/empty/over-cap trimming to 3.
- Build flow: in the aiuibuilder `/build` route path for NON-template builds (template_key falsy), before dispatching the normal pipeline, run the question pass via the existing single-shot claude call mechanism (find how clarify uses `_stream_claude`/subprocess for one-shot and reuse). Questions found -> task status `awaiting_input`, store `questions_json` + `questions_asked_at`, DO NOT start the build. `BuildStatusResponse` gains `questions: list | None` (from `questions_json`).
- Answer: extend the existing `/build/{task_id}/answer` request model with optional `answers: list[str] | None`; when present, append `\n\nUser choices:\n- <q> -> <answer>` lines to the task description, clear `questions_json`, resume via the same resume path free-text answers use. Also accept the literal answer `"__skip__"` (or `answers=[]`) -> resume with description unchanged plus a line "User skipped the questions; use sensible defaults."
- Timeout sweep: in `scheduler.schedule_tick_loop`'s tick (or a small companion check in `_tick_once`), tasks in `awaiting_input` WITH `questions_json` older than 10 minutes -> auto-skip (same as `__skip__`). Never touches the Jul-13 mid-build questions (those have `questions_json` NULL).
- `TasksClient.answer_build(...)`: extend the existing answer client method with `answers: list[str] | None = None` (read its current signature first; keep back-compat).

**Steps:** TDD: prompt/parse pure tests (NO_QUESTIONS, valid, garbage, 5-question payload trims to 3); answer-model shape tests; timeout-sweep test with monkeypatched session like scheduler tests if feasible, else route/logic factored into a pure helper `questions_timed_out(asked_at, now) -> bool` with tests. Regression: `tests/test_schedule_kind.py`, aiuibuilder route tests, the Jul-13 answer tests MUST stay green. Commit `feat(appbuilder): pre-build clarifying questions backend`.

---

### Task 7: Questions on web, Discord, Slack

**Files:** Modify `mcp-servers/tasks/static/projects.html` (or wherever the web build form lives - grep for the build POST), `webhook-handler/handlers/app_builder_panel.py`, `webhook-handler/handlers/discord_commands.py`, `webhook-handler/handlers/commands.py`, `webhook-handler/handlers/slack_app_builder_panel.py`, `webhook-handler/handlers/slack_interactions.py`. Create `webhook-handler/tests/test_prebuild_questions_surfaces.py`.

**Interfaces:**
- All surfaces poll/receive build status already (find how each surface currently reports build progress and the Jul-13 free-text question display; EXTEND those paths): when `questions` is present, render each question with its option buttons plus one "Just build it" skip.
- Discord: option custom_id `aiuibuild:qopt:<task_id>:<qi>:<oi>`, skip `aiuibuild:qskip:<task_id>`. Selecting an option updates a per-task pending-answers dict on the handler (like `_pending_schedules`); when all questions answered (or skip), call the extended `answer_build` client method and confirm in-thread.
- Slack: same semantics with block buttons in the DM; action_ids mirror Discord's.
- Web: the build form's status area renders question cards with option buttons; clicking posts to the answer endpoint with `answers`; skip button sends `__skip__`.
- Consumes Task 6's API shapes exactly.

**Steps:** TDD on builders + handlers with established fixtures; cover: buttons render per question, partial answers accumulate, full answers call client once with ordered answers, skip works, mid-build free-text questions (questions=None, question=str) still render the Jul-13 way. Commit `feat(appbuilder): pre-build questions on web, Discord, Slack`.

---

### Task 8: Final review + suites

Dash-scan the branch diff additions (U+2013/U+2014 -> zero). Full sweeps: tasks feature files (`test_app_versions*.py`, `test_app_smoke.py`, `test_autofix_loop.py`, `test_prebuild_questions.py`, plus regression `tests/ -q --ignore=tests/test_scheduler.py -k "aiuibuilder or schedule or video"`), webhook feature + regression files. Dispatch a whole-branch code review (most capable model) against the spec with the review package script; fix Critical/Important; merge to main and push after clean.

### Task 9: Deploy + live verification

Tar-push changed files (orchestrator's rsync is broken on this box), rebuild `tasks` + `webhook-handler`, run migration check (`\d tasks.<task table>` shows questions_json), update `.deploy-state`. Live verify: (1) blank build from Discord -> questions appear with buttons -> answer -> build completes -> `GET /{slug}/versions` shows v1; (2) enhance the app -> v2 appears; restore v1 from the web panel -> preview shows v1 content and v3 (pre-restore) exists; (3) check an execution log for the `--- AUTOFIX` section on a build with an injected error if feasible, else confirm smoke runs clean on a normal build (log line). healthz green. Update memory sync state.
