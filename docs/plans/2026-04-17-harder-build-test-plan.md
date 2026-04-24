# Harder-Build Test — Execution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan task-by-task.

**Goal:** Run the Ralph Loop pipeline on a multi-step task (meeting notes web app with SQLite + Prisma) and document where it succeeds or breaks.

**Architecture:** Task already queued in the tasks service (`tasks.items` row with `max_attempts=3`, loop mode). Admin drives the pipeline through the AIUI panel while monitoring via API / DB. Each failure becomes a data point for the Monday standup report.

**Tech Stack:** AIUI task panel (vanilla JS), tasks FastAPI service, Claude CLI, SQLite + Prisma (inside Claude's built app), SSH + curl for verification.

**Design:** See `docs/plans/2026-04-17-harder-build-test-design.md`

---

### Task 1: Pre-flight verification

**Goal:** Confirm the test task exists and the system is ready.

**Files:**
- Read-only: `tasks.items` row `16737bca-f408-455e-ba3a-165d44b0a445`

**Step 1: Verify task exists in DB with correct settings**

Run from local machine:
```bash
ssh root@46.224.193.25 'docker exec tasks python -c "
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(os.environ[\"DATABASE_URL\"])
    row = await conn.fetchrow(
        \"SELECT status, max_attempts, attempt_count, description FROM tasks.items WHERE id=\\$1\",
        \"16737bca-f408-455e-ba3a-165d44b0a445\"
    )
    print(row)
    await conn.close()
asyncio.run(check())
"'
```

Expected: `status=pending`, `max_attempts=3`, `attempt_count=0`, description contains "Prisma" and "SQLite".

**Step 2: Verify tasks service is up**

```bash
ssh root@46.224.193.25 "docker exec tasks curl -s http://localhost:8210/health"
```

Expected: `{"status":"ok","service":"tasks"}`

**Step 3: Verify latest panel JS is served past Cloudflare**

```bash
curl -s "https://ai-ui.coolestdomain.win/tasks/static/task-panel.js?v=check" | grep -c "previewBtnBig"
```

Expected: `2` (meaning the prominent Preview App button code is present)

**Step 4: No commit needed — this is verification only.**

---

### Task 2: Open AIUI and hard-refresh

**Goal:** Load the latest panel JS in the browser.

**Step 1: Open browser**

Navigate to https://ai-ui.coolestdomain.win in a fresh browser tab (not pinned, not in incognito — use your normal logged-in session).

**Step 2: Hard refresh**

Press `Ctrl + Shift + R` once the page loads.

**Step 3: Open the task panel**

Top-right floating panel. Click the header if minimized. Switch to the **Pending** tab.

**Step 4: Verify test task appears**

You should see a card with description starting "Build a shared meeting notes web app..." — with a purple `Loop 0/3` badge.

Expected: the task card visible in Pending tab with three buttons: **💬 Clarify**, **📋 Plan**, **⚡ AI**.

If not visible: check `tasks.items` filter — your user email (`alamajacintg04@gmail.com`) must match the task's `assignee_email`.

**Step 5: No commit — verification only.**

---

### Task 3: Run CLARIFY phase

**Goal:** Let Claude ask clarifying questions and capture the Q&A.

**Step 1: Click the Clarify button**

On the meeting-notes task card, click the purple **💬 Clarify** button.

**Step 2: Panel auto-switches to In Progress tab**

You should see a live streaming log. Watch for Claude's output.

**Step 3: Wait for first NEEDS_INPUT**

Usually appears within 30-90 seconds. Task status changes from `running` to `awaiting_input`. Panel switches back to Pending tab automatically; card now shows **⚠️ NEEDS INPUT** badge and Claude's question in an orange box.

**Step 4: Answer Claude's question**

Type your answer in the textarea, click **↩ Reply**.

Likely question types:
- Framework preferences — answer: *"Node/Express for backend, vanilla HTML/JS for frontend"*
- Specific fields — answer: *"Meeting: title, date, optional attendees text field. Note: body text, created timestamp"*
- Authentication — answer: *"No auth needed — single team use"*
- UI polish — answer: *"Dark theme, simple, functional over fancy"*

**Step 5: Repeat until CLARIFY_DONE**

Claude may ask 2-4 rounds. After enough context, it outputs `CLARIFY_DONE:` and auto-advances to the PLAN phase (status → `planning`).

**Step 6: Screenshot the Q&A history**

For the Monday report. The conversation history is also stored in `tasks.items.conversation_history` as JSONB — can be retrieved later.

**Step 7: No commit — test data only.**

---

### Task 4: Review and approve the plan

**Goal:** Confirm Claude's plan includes Prisma + SQLite + all features, then approve.

**Step 1: Wait for PLAN phase to complete**

Status auto-advances through `planning` → `awaiting_plan_review` (usually 1-2 minutes). Card shows the plan in a green box with two buttons: **✓ Approve Plan** / **✗ Reject**.

**Step 2: Read the plan carefully**

Checklist — the plan MUST mention:
- [ ] **SQLite** as the datasource (not PostgreSQL, not MySQL)
- [ ] **Prisma** as the ORM
- [ ] Express (or similar lightweight Node server)
- [ ] A `Meeting` model with title + date
- [ ] A `Note` model with body and foreign key to Meeting
- [ ] CRUD API routes for meetings and notes
- [ ] A search endpoint that filters notes by keyword
- [ ] `npx prisma migrate dev` step for initial migration
- [ ] A test file with at least smoke tests

**Step 3: Decide approve or reject**

- All boxes checked → click **✓ Approve Plan**
- Missing Prisma or SQLite → click **✗ Reject** and in the feedback modal type: *"Must use Prisma with SQLite datasource. Do not use raw SQL or any other database."* Then click Reject. Claude will re-plan.

**Step 4: Save the plan text**

Copy the plan content to `/tmp/meeting-notes-plan.md` on your local machine for the Monday report. It's also stored in `tasks.items.plan` column.

**Step 5: No commit — this is reviewing AI's plan, not our code.**

---

### Task 5: Trigger TDD EXECUTE phase

**Goal:** Let Claude build the app with Red-Green-Refactor.

**Step 1: Click ⚡ AI on the task card**

The task status goes back to `pending` after plan approval with `plan_status=approved`. Click **⚡ AI**.

**Step 2: Panel switches to In Progress tab**

Live stream shows Claude working through the plan. Expect to see:
- Writing failing test files
- Running tests (expecting fail)
- Creating source files
- Running tests again (expecting pass)
- Running `npx prisma generate` / `migrate`
- Committing per Red-Green cycle

**Step 3: Do NOT close the browser tab**

Streaming continues over SSE. Closing the tab doesn't cancel the task (it runs server-side), but you lose the live view. You can refresh to reconnect.

**Step 4: Expected duration**

5-15 minutes for a first attempt. Longer if retries fire.

**Step 5: Monitor for outcome**

One of:
- `COMPLETED: <summary>` — task auto-advances to VERIFY
- `NEEDS_INPUT: <question>` — back to awaiting_input, answer and resume
- `FAILED: <error>` — auto-retry fires if `attempt_count < max_attempts`

**Step 6: If a retry fires**

Badge updates to `Loop 1/3` or `Loop 2/3`. Watch for what error context the retry gets — the log will show "PREVIOUS ATTEMPT ({n}/3) FAILED: {error}" injected into the new prompt.

**Step 7: No commit during execution.**

---

### Task 6: Monitor VERIFY phase

**Goal:** Let the automatic verification run and catch any issues.

**Step 1: VERIFY runs automatically after COMPLETED**

Log marker: `--- VERIFY STEP ---` appears in the execution log. A second Claude subprocess checks the built app.

**Step 2: Watch for TESTS_PASSED or TESTS_FAILED**

- `TESTS_PASSED: <summary>` → task moves to Done tab, blue Preview App button appears
- `TESTS_FAILED: <details>` → auto-retry fires the whole TDD EXECUTE with verification errors as context

**Step 3: If TESTS_FAILED triggers max retries**

After 3 failed verifications, task goes to `failed` status. Read the last execution's log in the DB:

```bash
ssh root@46.224.193.25 'docker exec tasks python -c "
import asyncio, asyncpg, os
async def last_log():
    conn = await asyncpg.connect(os.environ[\"DATABASE_URL\"])
    row = await conn.fetchrow(
        \"SELECT status, error, log FROM tasks.executions WHERE task_id=\\$1 ORDER BY started_at DESC LIMIT 1\",
        \"16737bca-f408-455e-ba3a-165d44b0a445\"
    )
    print(\"status:\", row[\"status\"])
    print(\"error:\", row[\"error\"])
    print(\"last 2000 chars of log:\")
    print((row[\"log\"] or \"\")[-2000:])
    await conn.close()
asyncio.run(last_log())
"'
```

Note the error in `/tmp/meeting-notes-failure.md`.

**Step 4: No commit yet.**

---

### Task 7: Preview the built app

**Goal:** Visually confirm the app works in the preview iframe.

**Step 1: Verify completion**

Task should appear in the **Done** tab with a big blue **🔍 Preview App →** button.

**Step 2: Click Preview App**

Opens `/tasks/static/preview.html?task=16737bca-f408-455e-ba3a-165d44b0a445` in a new tab.

**Step 3: Verify file tree shows expected files**

Left sidebar should list:
- `package.json`
- `prisma/schema.prisma`
- `server.js`
- `public/index.html`
- `public/app.js`
- `public/style.css`
- `tests/test.js`
- (maybe) `prisma/migrations/` folder
- (maybe) `dev.db`

If any critical files are missing, note it for the report.

**Step 4: Click Run button (top right of preview page)**

The preview page calls `POST /api/tasks/{id}/preview/start` which spawns `npm install && npm run dev` (since there's a `package.json`) on port 9100.

**Step 5: Wait 15-30 seconds**

Status bar should show "Running on port 9100" (dot turns green). `npm install` takes time on first boot.

**Step 6: Click Preview tab**

iframe should load the meeting notes app at `/tasks/preview-app/`.

**Step 7: Manually test each feature**

- Add a meeting — enter title + date, submit → verify it appears in the list
- Add a note to the meeting → verify it's listed under that meeting
- Search for a note by keyword → verify filtered results
- Delete a note → verify it disappears
- Delete a meeting → verify cascade (notes also gone)

**Step 8: Screenshot each working feature** for the Monday report.

**Step 9: If any feature is broken**

Note it. This tells us the VERIFY step isn't thorough enough (it said tests passed, but the app doesn't actually work). That's valuable feedback to improve the VERIFY prompt.

**Step 10: No commit yet.**

---

### Task 8: Capture measurements for Monday's report

**Goal:** Gather all the test data into one place.

**Step 1: Get final task state**

```bash
ssh root@46.224.193.25 'docker exec tasks python -c "
import asyncio, asyncpg, os, json
async def report():
    conn = await asyncpg.connect(os.environ[\"DATABASE_URL\"])
    task = await conn.fetchrow(
        \"SELECT status, attempt_count, built_app_slug, plan_status, result, completed_at, created_at FROM tasks.items WHERE id=\\$1\",
        \"16737bca-f408-455e-ba3a-165d44b0a445\"
    )
    execs = await conn.fetch(
        \"SELECT status, error, started_at, finished_at, length(log) AS log_bytes FROM tasks.executions WHERE task_id=\\$1 ORDER BY started_at\",
        \"16737bca-f408-455e-ba3a-165d44b0a445\"
    )
    history = await conn.fetchval(
        \"SELECT conversation_history FROM tasks.items WHERE id=\\$1\",
        \"16737bca-f408-455e-ba3a-165d44b0a445\"
    )
    print(\"=== TASK ===\")
    for k, v in task.items():
        print(f\"{k}: {v}\")
    print(\"\\n=== EXECUTIONS ===\")
    for e in execs:
        print(dict(e))
    print(\"\\n=== Q&A HISTORY ===\")
    print(json.dumps(history, indent=2, default=str))
    await conn.close()
asyncio.run(report())
"' > /tmp/meeting-notes-report.txt
```

**Step 2: Get file listing of built app**

```bash
ssh root@46.224.193.25 "docker exec tasks ls -la /workspace/ai_ui/apps/meeting-notes/"
ssh root@46.224.193.25 "docker exec tasks find /workspace/ai_ui/apps/meeting-notes/ -type f"
```

**Step 3: Verify Prisma was actually used**

```bash
ssh root@46.224.193.25 "docker exec tasks cat /workspace/ai_ui/apps/meeting-notes/prisma/schema.prisma"
```

Expected: the file exists and `provider = "sqlite"` is present. If this check fails, Claude didn't follow Lukas's requirement.

**Step 4: Write the report to docs/plans/**

Create `docs/plans/2026-04-17-harder-build-test-result.md` with the following template:

```markdown
# Harder-Build Test — Result Report

**Date:** 2026-04-17
**Task ID:** 16737bca-f408-455e-ba3a-165d44b0a445

## Outcome
- Final status: [completed | failed]
- Attempt count: [0-3]
- Wall-clock time: [HH:MM]
- Built app slug: [meeting-notes | none]

## Used Prisma? [yes | no]
- Evidence: [paste schema.prisma first 10 lines or "file missing"]

## Pipeline phases — what fired
- [ ] CLARIFY — rounds: [N]
- [ ] PLAN — approved: [yes/no/rejected-once]
- [ ] TDD EXECUTE — attempts: [N]
- [ ] VERIFY — passed: [yes/no]
- [ ] PREVIEW — app served: [yes/no]

## Feature verification (manual)
- [ ] Add meeting works
- [ ] Add note works
- [ ] List meetings works
- [ ] Search notes works
- [ ] Delete meeting works (cascade)
- [ ] Delete note works

## Failures / Retries
For each failure or retry: attempt number, phase, error, what Claude did next.

## Observations
Qualitative notes: clarify question quality, plan readability, preview UX, anything surprising.

## Recommended next actions
What to change based on this test (prompt tweaks, timeout adjustments, new scope rules, etc.)
```

**Step 5: Commit the report**

```bash
git add docs/plans/2026-04-17-harder-build-test-result.md
git commit -m "docs(plans): harder-build test result report"
```

---

### Task 9: Decide next action

**Goal:** Based on results, choose follow-up.

**Step 1: Compare outcome to success criteria from design doc**

From `docs/plans/2026-04-17-harder-build-test-design.md`:
1. Prisma + SQLite used? (required)
2. Full pipeline fired? (required)
3. Auto-retry triggered once? (success indicator)
4. App actually works? (required)

**Step 2: Pick the next action**

- **All criteria met, zero retries:** loop is too easy for this task. Design a harder test (Approach: add OAuth, or real-time updates via WebSockets).
- **All met, 1-2 retries:** loop is working as designed. Queue PR of `feat/decision-engine-loop-preview` to main.
- **Failed (3 retries exhausted):** do NOT PR yet. Analyze failure phase, propose a fix (usually prompt tuning in `claude_executor.py`), and re-run test after fix.

**Step 3: Update project memory**

Add the outcome to `memory/project_decision_engine_roadmap.md` so future sessions know Phase 2/3 state.

**Step 4: Commit memory update** (if any)

```bash
# Memory updates go to user's .claude dir, no git commit needed
```

**Step 5: Post result summary in Monday standup**

Lead with the headline: *"Loop survived N retries on a Prisma+SQLite build — here's what we learned"* or *"Loop broke at phase X — here's the fix"*.

---

## Skills referenced
- `@superpowers:executing-plans` — for executing this plan
- `@superpowers:systematic-debugging` — if failures need investigation
- `@superpowers:verification-before-completion` — before claiming success in the Monday report
