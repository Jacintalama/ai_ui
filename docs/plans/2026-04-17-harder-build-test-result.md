# Harder-Build Test — Result Report

**Date:** 2026-04-17 (executed 2026-04-21 because of Cloudflare cache testing delays earlier)
**Task ID:** `16737bca-f408-455e-ba3a-165d44b0a445`
**Design doc:** `docs/plans/2026-04-17-harder-build-test-design.md`
**Execution plan:** `docs/plans/2026-04-17-harder-build-test-plan.md`

## Headline

**The loop survived.** Task completed on attempt 3 of 3. Two auto-retries fired. The built app works end-to-end via API. BUT — the test also uncovered three real bugs in our pipeline.

## Outcome

| Metric | Value |
|---|---|
| Final status | `completed` |
| Attempt count | 2 (= 3rd attempt succeeded; 0-indexed) |
| Wall-clock duration | **1868 seconds (31 minutes 8 seconds)** |
| Built app slug | `meeting-notes` |
| plan_status | **None** — PLAN phase never ran (see bug #1) |

## Did Claude use Prisma?

**NO.** Claude pivoted from Node/Express/Prisma to **Python/Flask/sqlite3** on attempt 3.

Evidence:
- Attempts 1 and 2: wrote Node/Express/Prisma code (`server.js`, `prisma/schema.prisma`, `prisma/migrations/`)
- Attempt 3: deleted those, wrote Python/Flask instead (`server.py`, uses stdlib `sqlite3` module)
- Final files: `server.py`, `test_api.py`, `public/index.html`, `package.json` (updated for Python scripts), `.gitignore`
- `prisma/schema.prisma` still exists as dead code from earlier attempts — never used at runtime

Implication: Claude ignored Lukas's explicit Prisma requirement when retrying. The prompt gets the task description each time, but when facing errors, Claude prioritizes getting *something* working over following every detail.

## Pipeline phases — what fired

| Phase | Fired? | Notes |
|---|---|---|
| CLARIFY | ✅ (1 round only) | Claude asked ONE question (auth model), admin answered, then... |
| PLAN | ❌ | Was skipped entirely. plan_status = None. Bug #1. |
| TDD EXECUTE | ✅ (3 attempts) | Failed twice, succeeded on 3rd |
| VERIFY | ❌ | Never ran. Bug #2. |
| PREVIEW (auto-start via button) | ❌ | app_runner assumed `npm run dev`. Bug #3. |

## Feature verification (manual, via curl)

All 6 spec features work when the Python server is run manually:

- ✅ `GET /api/meetings` — list meetings chronologically
- ✅ `POST /api/meetings` — create meeting (title + date)
- ✅ `POST /api/meetings/:id/notes` — add note to meeting
- ✅ `GET /api/search?q=keyword` — search notes (returns notes + embedded meeting context)
- ✅ `DELETE /api/notes/:id` — delete single note
- ✅ `DELETE /api/meetings/:id` — delete meeting with CASCADE (notes also deleted)

Test data: created "April 17 standup" meeting, added 2 notes, searched for "SQLite" (matched 1), deleted note 1, deleted meeting 1 (cascade removed note 2).

## Bugs uncovered (the valuable part)

### Bug #1 — /answer endpoint short-circuits CLARIFY phase
**Location:** `mcp-servers/tasks/routes_tasks.py` — `answer` endpoint, `awaiting_input` branch.

**What happens:** After the first NEEDS_INPUT round and admin answer, the endpoint builds a prompt using `build_tdd_execute_prompt()` or legacy `build_prompt()` — neither is `build_clarify_prompt()`. So Claude is no longer in CLARIFY mode. It sees the plan-less execute prompt and starts building immediately. Result: only ONE clarify question ever gets asked; PLAN phase is skipped entirely.

**Evidence:**
- conversation_history length = 2 (one Q, one A)
- plan_status stayed `None`
- Claude's result text begins: *"Let me first check the current state of the previous attempt. Now let me write the test file first (RED phase)..."*

**Fix:** in `routes_tasks.py::answer`, detect whether we came from CLARIFY (e.g., by checking if `plan` is None AND task has loop mode) and in that case call `build_clarify_prompt()` instead of TDD/legacy prompts.

### Bug #2 — VERIFY step never ran
**Location:** `mcp-servers/tasks/routes_execution.py` — `_run_execution`.

**What happens:** VERIFY only fires when `outcome.kind == "completed" AND is_loop AND slug` — and even then only inside the initial execute path. But because Bug #1 short-circuited into legacy `build_prompt` mode (which uses the basic executor), the COMPLETED sentinel landed but the VERIFY block didn't trigger. So we skipped verification despite being in loop mode.

**Fix:** audit the VERIFY trigger condition. It should fire whenever `is_loop` and COMPLETED is reached, regardless of which prompt path produced the completion.

### Bug #3 — app_runner assumes `npm run dev`
**Location:** `mcp-servers/tasks/app_runner.py` — `start_preview`.

**What happens:** If `package.json` exists, runner hardcodes `npm install && npm run dev -- --port {port}`. But Claude's final `package.json` has only `start` and `test` scripts (no `dev`). Runner tried, failed silently, status returned `running: false`.

Also: the runner forwards `--port {port}` as an argument, which only works for JS frameworks that respect it. Python apps read `PORT` from env.

**Fix options:**
- Try `npm run dev` → fall back to `npm run start` if dev script missing
- Detect interpreter from package.json `main` or first key in `scripts`
- Pass port via both env var AND arg
- Add Python support: if `server.py` or `main.py` exists, run `python3 server.py` with `PORT=9100` env

**Workaround used during test:** Manually started Python server with `docker exec -d tasks sh -c 'cd apps/meeting-notes && PORT=9100 python3 server.py'` after running `pip install flask`.

## Observations

- **Loop retry logic is solid.** 2 failed attempts → error context appended → 3rd attempt succeeded. The auto-retry is what makes the loop valuable.
- **Claude pivots on failure.** When retry fires with error context, Claude may switch technology stacks. This is good for robustness but means the task description isn't sticky across retries. We should consider restating requirements in the retry prompt.
- **The CLARIFY design assumed a tight loop.** The implementation doesn't actually loop — one answer ends clarify and starts build. Fixing this correctly means routing the answer back through `build_clarify_prompt` until `CLARIFY_DONE`.
- **Preview page UX was fine.** The slug-mismatch detection + cache-bust iframe from yesterday's fix handled the "wrong app" case correctly.
- **31 minutes for a task this size is long** but acceptable — most of it was 2 failed attempts (~3 minutes each) plus installation/migration time.

## What to bring to Monday's standup

1. **Good news:** Ralph Loop retry mechanism works — built a real multi-file app after 2 retries
2. **Bad news:** CLARIFY phase is broken (single-round only), PLAN phase is skipped, VERIFY phase is skipped, preview auto-start is broken for non-standard package.json
3. **Product pitch still holds:** a non-programmer answers one question, AI produces a working web app with CRUD + search + cascading delete
4. **Next backlog items** (3 bugs above, each with specific file + fix)

## Recommended next actions (priority order)

1. **Fix Bug #1** (CLARIFY short-circuit) — this is the biggest one. It breaks Lukas's "plan mode" vision. File: `mcp-servers/tasks/routes_tasks.py`
2. **Fix Bug #2** (VERIFY trigger) — critical for product correctness. File: `mcp-servers/tasks/routes_execution.py`
3. **Fix Bug #3** (preview runner flexibility) — less critical, only hits when Claude picks non-standard stack. File: `mcp-servers/tasks/app_runner.py`
4. **Re-run this exact test** after fixes to confirm the full CLARIFY → PLAN → EXECUTE → VERIFY pipeline actually fires
5. **Then** PR `feat/decision-engine-loop-preview` to main
