# Decision Engine: Loop Mode + Preview Page — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Ralph's Loop (auto-retry, plan step, test step, multi-turn NEEDS_INPUT) and a Codex-style preview page to the tasks service.

**Architecture:** Extend the existing tasks service (`mcp-servers/tasks/`) with new DB columns, a pipeline executor (plan → execute → test → retry), and a new preview page with file tree + iframe app runner. All within the same container.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, asyncpg, PostgreSQL, vanilla JS (zero deps), highlight.js (CDN), npx serve

---

### Task 1: Database Migration — New Columns

**Files:**
- Create: `mcp-servers/tasks/migrations/002_loop_and_preview.sql`

**Step 1: Write the migration**

```sql
-- Loop mode columns
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS max_attempts    INT NOT NULL DEFAULT 1;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS attempt_count   INT NOT NULL DEFAULT 0;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS conversation_history JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS plan            TEXT;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS plan_status     TEXT CHECK (plan_status IN ('pending_review','approved','rejected'));
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS built_app_slug  TEXT;

-- Expand the status CHECK to include new states
ALTER TABLE tasks.items DROP CONSTRAINT IF EXISTS items_status_check;
ALTER TABLE tasks.items ADD CONSTRAINT items_status_check
    CHECK (status IN ('pending','planning','awaiting_plan_review','claimed_manual','running','awaiting_input','completed','failed'));
```

**Step 2: Verify locally**

Run: `cat mcp-servers/tasks/migrations/002_loop_and_preview.sql`
Expected: The SQL above, valid PostgreSQL DDL.

**Step 3: Commit**

```bash
git add mcp-servers/tasks/migrations/002_loop_and_preview.sql
git commit -m "feat(tasks): add migration 002 — loop mode + preview columns"
```

---

### Task 2: Update ORM Models + Schemas

**Files:**
- Modify: `mcp-servers/tasks/models.py:5-35`
- Modify: `mcp-servers/tasks/schemas.py:1-63`

**Step 1: Add new columns to TaskItem model**

In `models.py`, add these imports and columns:

```python
# Add to imports (line 5):
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Add after line 28 (after `mode` column):
    max_attempts = Column(Integer, nullable=False, default=1)
    attempt_count = Column(Integer, nullable=False, default=0)
    conversation_history = Column(JSONB, nullable=False, default=list)
    plan = Column(Text, nullable=True)
    plan_status = Column(Text, nullable=True)
    built_app_slug = Column(Text, nullable=True)
```

**Step 2: Update schemas**

In `schemas.py`:

```python
# Update Status literal (line 10):
Status = Literal["pending", "planning", "awaiting_plan_review", "claimed_manual", "running", "awaiting_input", "completed", "failed"]

# Add PlanStatus type:
PlanStatus = Literal["pending_review", "approved", "rejected"]

# Add new fields to TaskOut (after line 25, before class Config):
    max_attempts: int = 1
    attempt_count: int = 0
    conversation_history: list = []
    plan: str | None = None
    plan_status: str | None = None
    built_app_slug: str | None = None

# Add to CreateTaskRequest (after line 62):
    max_attempts: int = Field(default=1, ge=1, le=10, description="1=one-shot, >1=loop mode")

# Add new request schemas at the end:
class PlanReviewRequest(BaseModel):
    approved: bool
    feedback: str = ""
```

**Step 3: Verify imports work**

Run: `cd mcp-servers/tasks && python -c "from models import TaskItem; from schemas import TaskOut, CreateTaskRequest; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add mcp-servers/tasks/models.py mcp-servers/tasks/schemas.py
git commit -m "feat(tasks): add loop + preview fields to ORM models and schemas"
```

---

### Task 3: Superpowers-style Prompts + Sentinels in claude_executor.py

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py:1-201`

This task rewrites the prompt templates to mirror the Superpowers skills flow:
- CLARIFY prompt → mirrors `superpowers:brainstorming` (structured Q&A, one question at a time)
- PLAN prompt → mirrors `superpowers:writing-plans` (business requirements + tech + test specs)
- EXECUTE prompt → mirrors `superpowers:test-driven-development` (red-green-refactor TDD)
- VERIFY prompt → final verification of the built app

**Step 1: Add new sentinel patterns**

After line 93 (`_SENTINEL_RE`), add:

```python
_CLARIFY_DONE_RE = re.compile(r"CLARIFY_DONE:\s*(?P<rest>.+)", re.DOTALL)
_PLAN_RE = re.compile(r"PLAN:\s*(?P<rest>.+)", re.DOTALL)
_TEST_RE = re.compile(
    r"(?P<kind>TESTS_PASSED|TESTS_FAILED):\s*(?P<rest>[^\n]*)",
    re.DOTALL,
)
_SLUG_RE = re.compile(r"apps/([a-z0-9_-]+)/")
```

**Step 2: Add Superpowers-style prompt templates**

After `build_prompt()` (line 83), add all prompt builders:

```python
# ---------------------------------------------------------------------------
# CLARIFY — mirrors superpowers:brainstorming
# ---------------------------------------------------------------------------
CLARIFY_PROMPT_TEMPLATE = """You are the AIUI meeting decision engine preparing to build something.

TASK FROM TRANSCRIPT: {description}
TYPE: {action_type}
PRIORITY: {priority}

Before writing ANY code, you MUST understand what to build.

RULES:
1. Ask ONE clarifying question at a time.
2. Prefer MULTIPLE CHOICE questions when possible, e.g.:
   "Which platform? (a) Web only (b) Mobile (c) Both"
   "What framework? (a) Vanilla HTML/CSS/JS (b) React (c) Vue (d) No preference"
3. Ask about: purpose, target users, key features, platform, tech preferences,
   success criteria, scope boundaries.
4. Minimum 2 questions before you can proceed.
5. Do NOT write any code. Do NOT plan yet. Only ask questions.

For each question, end your response with:
  NEEDS_INPUT: <your question>

When you have gathered enough information to write a detailed plan, end with:
  CLARIFY_DONE: <one-paragraph summary of gathered requirements>"""

{conversation_history_block}


# ---------------------------------------------------------------------------
# PLAN — mirrors superpowers:writing-plans
# ---------------------------------------------------------------------------
PLAN_PROMPT_TEMPLATE = """You are creating an implementation plan for the AIUI decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}

GATHERED REQUIREMENTS:
{requirements}

Create a DETAILED implementation plan with these EXACT sections:

## 1. BUSINESS REQUIREMENTS
- What the user needs and why
- Success criteria (how do we know it's done?)
- Scope boundaries (what is explicitly OUT of scope)

## 2. TECHNICAL BREAKDOWN
- Architecture: files to create, components, data flow
- Exact file paths under apps/<slug>/ (e.g. apps/todo-organizer/index.html)
- Dependencies (if any — prefer zero-dep vanilla JS for simple apps)

## 3. TEST SPECIFICATIONS
- List each test to write BEFORE implementation
- What each test verifies (expected behavior, not implementation details)
- Edge cases to cover (empty state, error handling, boundary values)
- For HTML/JS apps: what to check (renders, interactions work, state persists)

## 4. IMPLEMENTATION STEPS
- Bite-sized tasks (one action each, 2-5 minutes)
- Each step: which file, what to write, which test it satisfies
- Order matters: tests FIRST, then implementation for each feature

Do NOT write any code. Plan only.
End your response with:
  PLAN: <your complete plan>"""


# ---------------------------------------------------------------------------
# EXECUTE — mirrors superpowers:test-driven-development (Red-Green-Refactor)
# ---------------------------------------------------------------------------
TDD_EXECUTE_PROMPT_TEMPLATE = """You are executing a BUILD task from the AIUI decision engine.

TASK: {description}
TYPE: {action_type}
PRIORITY: {priority}
SOURCE: {meeting_title} on {meeting_date}

Repository: /workspace/ai_ui (git working tree).

APPROVED PLAN:
{plan}

{conversation_history_block}

{error_context_block}

YOU MUST FOLLOW TEST-DRIVEN DEVELOPMENT. This is not optional.

For EACH feature in the plan, follow Red-Green-Refactor:

  RED — Write a failing test first. The test defines the expected behavior.
        For HTML/JS apps, write a test file (e.g. apps/<slug>/tests/test.html
        or apps/<slug>/test.js) that checks the feature works.
        Run it. Confirm it fails because the feature is missing.

  GREEN — Write the MINIMAL code to make the test pass. Nothing extra.
          Do NOT add features beyond what the test requires.
          Run the test. Confirm it passes.

  REFACTOR — Clean up if needed. Keep tests passing.

SCOPE RULES:
  1. Build ONLY what the plan describes. Do not infer extra scope.
  2. Prefer the SIMPLEST solution (vanilla HTML/CSS/JS with localStorage
     unless the plan explicitly calls for a framework/backend).
  3. Place apps under apps/<slug>/ (e.g. apps/todo-list/index.html).
  4. Do NOT add auth, Docker, FastAPI, or deployment unless the plan says so.

GIT RULES:
  1. Stage just the files you changed: git add <path1> <path2> ...
     (do NOT git add -A or git add . — only stage what you intentionally edited)
  2. Commit after each Red-Green cycle: git commit -m "<what this step adds>"
  3. Do NOT push.

When ALL tests pass and the app is complete:
  COMPLETED: <summary of what you built + list of commit hashes>

If you cannot proceed:
  NEEDS_INPUT: <what you need from the admin>
  FAILED: <what went wrong>"""


# ---------------------------------------------------------------------------
# VERIFY — separate verification subprocess
# ---------------------------------------------------------------------------
VERIFY_PROMPT_TEMPLATE = """You are verifying a completed build task.

The app was built at: apps/{slug}/
Task description: {description}

Run a thorough verification:
1. Check all expected files exist (per the plan)
2. Open/parse HTML files — valid structure, no broken references
3. Check JavaScript — no syntax errors, logic matches requirements
4. Run any test files that exist (apps/{slug}/tests/ or apps/{slug}/test.*)
5. Verify the app matches what was requested in the task description

If everything works correctly:
  TESTS_PASSED: <one-line summary of what was verified>

If something is broken:
  TESTS_FAILED: <specific list of what's wrong and how to fix each issue>"""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------
def _format_conversation_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for entry in history:
        role = "AI asked" if entry["role"] == "ai" else "Admin answered"
        lines.append(f"  {role}: {entry['content']}")
    return "CONVERSATION HISTORY:\n" + "\n".join(lines)


def build_clarify_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    conversation_history: list[dict],
) -> str:
    history_block = _format_conversation_history(conversation_history)
    template = CLARIFY_PROMPT_TEMPLATE.replace(
        "{conversation_history_block}", history_block
    )
    return template.format(
        description=description,
        action_type=action_type,
        priority=priority,
    )


def build_plan_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    requirements: str = "",
) -> str:
    return PLAN_PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        requirements=requirements or "(no clarification — task was clear enough)",
    )


def build_tdd_execute_prompt(
    *,
    description: str,
    action_type: str,
    priority: str,
    meeting_title: str,
    meeting_date: str,
    plan: str,
    conversation_history: list[dict],
    attempt_count: int = 0,
    max_attempts: int = 1,
    error_context: str = "",
) -> str:
    history_block = _format_conversation_history(conversation_history)
    if error_context:
        error_block = (
            f"PREVIOUS ATTEMPT ({attempt_count}/{max_attempts}) FAILED:\n"
            f"{error_context}\n"
            "Fix the issues above. Do NOT repeat the same mistake."
        )
    else:
        error_block = ""
    return TDD_EXECUTE_PROMPT_TEMPLATE.format(
        description=description,
        action_type=action_type,
        priority=priority,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
        plan=plan,
        conversation_history_block=history_block,
        error_context_block=error_block,
    )


def build_verify_prompt(*, slug: str, description: str) -> str:
    return VERIFY_PROMPT_TEMPLATE.format(slug=slug, description=description)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_clarify_done(claude_response: str) -> str | None:
    """Extract requirements summary after CLARIFY_DONE sentinel."""
    text = _extract_assistant_text(claude_response) or claude_response
    match = _CLARIFY_DONE_RE.search(text)
    return match.group("rest").strip() if match else None


def parse_plan(claude_response: str) -> str | None:
    text = _extract_assistant_text(claude_response) or claude_response
    match = _PLAN_RE.search(text)
    return match.group("rest").strip() if match else None


@dataclass(frozen=True)
class TestOutcome:
    passed: bool
    detail: str


def parse_test_outcome(claude_response: str) -> TestOutcome:
    text = _extract_assistant_text(claude_response) or claude_response
    matches = list(_TEST_RE.finditer(text))
    if not matches:
        return TestOutcome(passed=False, detail="No test sentinel found in output")
    last = matches[-1]
    return TestOutcome(
        passed=last.group("kind") == "TESTS_PASSED",
        detail=last.group("rest").strip(),
    )


def extract_app_slug(claude_response: str) -> str | None:
    text = _extract_assistant_text(claude_response) or claude_response
    match = _SLUG_RE.search(text)
    return match.group(1) if match else None
```

**Step 3: Commit**

```bash
git add mcp-servers/tasks/claude_executor.py
git commit -m "feat(tasks): Superpowers-style prompt templates — clarify, plan, TDD execute, verify"
```

---

### Task 4: Superpowers Pipeline Executor — Clarify, Plan, TDD Execute, Verify

**Files:**
- Modify: `mcp-servers/tasks/routes_execution.py:1-227`

The pipeline has 4 phases, each a separate Claude subprocess. Admin can observe
and interact between phases via the panel.

```
CLARIFY (Q&A rounds) → PLAN (detailed) → Admin Review → TDD EXECUTE → VERIFY → retry
```

**Step 1: Update imports at top of file**

```python
from claude_executor import (
    build_prompt, build_clarify_prompt, build_plan_prompt,
    build_tdd_execute_prompt, build_verify_prompt,
    extract_app_slug, parse_outcome, parse_clarify_done,
    parse_plan, parse_test_outcome, run_claude_subprocess,
)
from schemas import PlanReviewRequest, TaskOut
```

**Step 2: Rewrite `_run_execution` to support the full pipeline**

Replace the `_run_execution` function (lines 28-110) with:

```python
async def _stream_claude(prompt: str, execution_id: UUID, task_id: UUID) -> str:
    """Run a Claude subprocess, stream output to execution log, return full output."""
    full_log: list[str] = []
    proc_holder = _RUNNING.get(task_id, {})
    async for chunk in run_claude_subprocess(prompt, proc_holder=proc_holder):
        full_log.append(chunk)
        async with session() as s:
            await s.execute(
                update(TaskExecution)
                .where(TaskExecution.id == execution_id)
                .values(log=TaskExecution.log + chunk)
            )
            await s.commit()
    return "".join(full_log)


async def _run_execution(task_id: UUID, execution_id: UUID, prompt: str):
    """Background coroutine: stream Claude output, parse outcome, persist.

    In loop mode (max_attempts > 1), handles auto-retry on failure
    and runs the VERIFY step after COMPLETED."""
    try:
        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == execution_id)
                .values(log="[spawning claude subprocess…]\n")
            )
            await s.commit()

        full_output = await _stream_claude(prompt, execution_id, task_id)
        outcome = parse_outcome(full_output)

        # Read current task state for loop decisions
        async with session() as s:
            task = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one()
            is_loop = task.max_attempts > 1
            attempt = task.attempt_count
            max_att = task.max_attempts

        # Extract app slug from completed BUILD tasks
        slug = None
        if outcome.kind == "completed":
            slug = extract_app_slug(full_output)

        # --- LOOP MODE: auto-retry on failure ---
        if outcome.kind == "failed" and is_loop and attempt < max_att:
            async with session() as s:
                await s.execute(
                    update(TaskExecution).where(TaskExecution.id == execution_id)
                    .values(status="failed", finished_at=datetime.utcnow(),
                            error=f"Attempt {attempt}/{max_att} failed — auto-retrying")
                )
                await s.execute(
                    update(TaskItem).where(TaskItem.id == task_id)
                    .values(attempt_count=attempt + 1, result=outcome.payload)
                )
                new_exec = TaskExecution(task_id=task_id, status="running", log="")
                s.add(new_exec)
                await s.commit()
                await s.refresh(new_exec)

            retry_prompt = build_tdd_execute_prompt(
                description=task.description,
                action_type=task.action_type,
                priority=task.priority,
                meeting_title=str(task.meeting_id),
                meeting_date="",
                plan=task.plan or "",
                conversation_history=task.conversation_history or [],
                attempt_count=attempt + 1,
                max_attempts=max_att,
                error_context=outcome.payload,
            )
            await _run_execution(task_id, new_exec.id, retry_prompt)
            return

        # --- LOOP MODE: VERIFY step after COMPLETED ---
        if outcome.kind == "completed" and is_loop and slug:
            async with session() as s:
                await s.execute(
                    update(TaskExecution).where(TaskExecution.id == execution_id)
                    .values(log=TaskExecution.log + "\n\n--- VERIFY STEP ---\n")
                )
                await s.commit()

            verify_output = await _stream_claude(
                build_verify_prompt(slug=slug, description=task.description),
                execution_id, task_id,
            )
            test_result = parse_test_outcome(verify_output)

            if not test_result.passed and attempt < max_att:
                async with session() as s:
                    await s.execute(
                        update(TaskExecution).where(TaskExecution.id == execution_id)
                        .values(status="failed", finished_at=datetime.utcnow(),
                                error=f"Verify failed: {test_result.detail}")
                    )
                    await s.execute(
                        update(TaskItem).where(TaskItem.id == task_id)
                        .values(attempt_count=attempt + 1,
                                result=f"Verify failed: {test_result.detail}")
                    )
                    new_exec = TaskExecution(task_id=task_id, status="running", log="")
                    s.add(new_exec)
                    await s.commit()
                    await s.refresh(new_exec)

                retry_prompt = build_tdd_execute_prompt(
                    description=task.description,
                    action_type=task.action_type,
                    priority=task.priority,
                    meeting_title=str(task.meeting_id),
                    meeting_date="",
                    plan=task.plan or "",
                    conversation_history=task.conversation_history or [],
                    attempt_count=attempt + 1,
                    max_attempts=max_att,
                    error_context=f"Build completed but verification failed: {test_result.detail}",
                )
                await _run_execution(task_id, new_exec.id, retry_prompt)
                return

        # --- Standard outcome handling ---
        new_task_status = {
            "completed": "completed",
            "needs_input": "awaiting_input",
            "needs_steps": "claimed_manual",
            "failed": "pending" if not is_loop else "failed",
        }[outcome.kind]
        new_exec_status = {
            "completed": "succeeded",
            "needs_input": "needs_input",
            "needs_steps": "succeeded",
            "failed": "failed",
        }[outcome.kind]
        mode_val = None if outcome.kind == "failed" else ("manual" if outcome.kind == "needs_steps" else "ai")

        # Store NEEDS_INPUT in conversation history
        history_update = {}
        if outcome.kind == "needs_input":
            history = list(task.conversation_history or [])
            history.append({"role": "ai", "content": outcome.payload, "attempt": attempt})
            history_update = {"conversation_history": history}

        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == execution_id)
                .values(status=new_exec_status, finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == task_id)
                .values(
                    status=new_task_status,
                    mode=mode_val,
                    result=outcome.payload,
                    completed_at=datetime.utcnow() if outcome.kind == "completed" else None,
                    built_app_slug=slug,
                    **history_update,
                )
            )
            await s.commit()
    except Exception as exc:
        logger.exception("Execution failed: %s", exc)
        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == execution_id)
                .values(status="failed", error=str(exc), finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == task_id).values(
                    status="pending", mode=None, result=f"Previous AI run failed: {exc}"[:500]
                )
            )
            await s.commit()
    finally:
        _RUNNING.pop(task_id, None)
```

**Step 3: Add CLARIFY endpoint (Superpowers brainstorming phase)**

After the existing `execute` endpoint (after line 156), add:

```python
@router.post("/{task_id}/clarify", response_model=TaskOut)
async def start_clarify(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Start the CLARIFY phase — Claude asks structured questions before planning."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
        if item.max_attempts <= 1:
            raise HTTPException(status_code=400, detail="Clarify only for loop mode")
        if item.status != "pending":
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")

        item.status = "running"
        item.mode = "ai"
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)

    prompt = build_clarify_prompt(
        description=item.description,
        action_type=item.action_type,
        priority=item.priority,
        conversation_history=item.conversation_history or [],
    )
    _RUNNING[item.id] = {"task": None, "proc": None}

    async def _clarify_bg(tid, eid, p):
        try:
            full_output = await _stream_claude(p, eid, tid)

            # Check if CLARIFY_DONE or NEEDS_INPUT
            done_text = parse_clarify_done(full_output)
            outcome = parse_outcome(full_output)

            async with session() as s:
                task = (await s.execute(select(TaskItem).where(TaskItem.id == tid))).scalar_one()
                history = list(task.conversation_history or [])

                if done_text:
                    # Clarification complete — move to PLAN phase
                    await s.execute(
                        update(TaskExecution).where(TaskExecution.id == eid)
                        .values(status="succeeded", finished_at=datetime.utcnow())
                    )
                    await s.execute(
                        update(TaskItem).where(TaskItem.id == tid).values(
                            status="planning",
                            result=done_text,
                        )
                    )
                    await s.commit()

                    # Auto-trigger plan step
                    plan_exec = TaskExecution(task_id=tid, status="running", log="")
                    s.add(plan_exec)
                    await s.commit()
                    await s.refresh(plan_exec)

                    plan_prompt = build_plan_prompt(
                        description=task.description,
                        action_type=task.action_type,
                        priority=task.priority,
                        requirements=done_text,
                    )
                    await _plan_bg(tid, plan_exec.id, plan_prompt)
                elif outcome.kind == "needs_input":
                    # Claude asked a question — pause for admin
                    history.append({"role": "ai", "content": outcome.payload, "attempt": 0})
                    await s.execute(
                        update(TaskExecution).where(TaskExecution.id == eid)
                        .values(status="needs_input", finished_at=datetime.utcnow())
                    )
                    await s.execute(
                        update(TaskItem).where(TaskItem.id == tid).values(
                            status="awaiting_input",
                            result=outcome.payload,
                            conversation_history=history,
                        )
                    )
                    await s.commit()
                else:
                    # Unexpected — treat as ready for plan
                    await s.execute(
                        update(TaskExecution).where(TaskExecution.id == eid)
                        .values(status="succeeded", finished_at=datetime.utcnow())
                    )
                    await s.execute(
                        update(TaskItem).where(TaskItem.id == tid).values(
                            status="pending", result="Clarify phase ended without CLARIFY_DONE"
                        )
                    )
                    await s.commit()
        except Exception as exc:
            logger.exception("Clarify step failed: %s", exc)
            async with session() as s:
                await s.execute(
                    update(TaskExecution).where(TaskExecution.id == eid)
                    .values(status="failed", error=str(exc), finished_at=datetime.utcnow())
                )
                await s.execute(
                    update(TaskItem).where(TaskItem.id == tid).values(status="pending", mode=None)
                )
                await s.commit()
        finally:
            _RUNNING.pop(tid, None)

    bg = asyncio.create_task(_clarify_bg(item.id, execution.id, prompt))
    _RUNNING[item.id]["task"] = bg
    return item
```

**Step 4: Add PLAN endpoint (Superpowers writing-plans phase)**

```python
async def _plan_bg(tid: UUID, eid: UUID, prompt: str):
    """Background: run plan subprocess, parse PLAN sentinel, await review."""
    try:
        full_output = await _stream_claude(prompt, eid, tid)
        plan_text = parse_plan(full_output)
        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == eid)
                .values(status="succeeded", finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == tid).values(
                    status="awaiting_plan_review",
                    plan=plan_text or full_output[-3000:],
                    plan_status="pending_review",
                )
            )
            await s.commit()
    except Exception as exc:
        logger.exception("Plan step failed: %s", exc)
        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == eid)
                .values(status="failed", error=str(exc), finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == tid).values(status="pending", mode=None)
            )
            await s.commit()
    finally:
        _RUNNING.pop(tid, None)


@router.post("/{task_id}/plan", response_model=TaskOut)
async def start_plan(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Manually trigger the PLAN phase (skips CLARIFY)."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
        if item.max_attempts <= 1:
            raise HTTPException(status_code=400, detail="Plan step only for loop mode")
        if item.status not in ("pending", "planning"):
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")

        item.status = "planning"
        item.mode = "ai"
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)

    requirements = item.result or ""  # CLARIFY_DONE summary if available
    prompt = build_plan_prompt(
        description=item.description,
        action_type=item.action_type,
        priority=item.priority,
        requirements=requirements,
    )
    _RUNNING[item.id] = {"task": None, "proc": None}
    bg = asyncio.create_task(_plan_bg(item.id, execution.id, prompt))
    _RUNNING[item.id]["task"] = bg
    return item


@router.post("/{task_id}/review-plan", response_model=TaskOut)
async def review_plan(task_id: UUID, body: PlanReviewRequest, user: AdminUser = Depends(current_admin)):
    """Admin approves or rejects a plan."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.status != "awaiting_plan_review":
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")
        if body.approved:
            item.plan_status = "approved"
            item.status = "pending"  # Ready for TDD execute
        else:
            item.plan_status = "rejected"
            item.status = "pending"
            item.plan = None
            if body.feedback:
                item.result = f"Plan rejected: {body.feedback}"
        await s.commit()
        await s.refresh(item)
    return item
```

**Step 5: Update the execute endpoint to use TDD prompt when plan exists**

Modify the `execute` endpoint's prompt building (lines 144-150):

```python
    # Build prompt — loop mode uses TDD execute with plan + history
    if item.max_attempts > 1 and item.plan and item.plan_status == "approved":
        prompt = build_tdd_execute_prompt(
            description=item.description,
            action_type=item.action_type,
            priority=item.priority,
            meeting_title=str(item.meeting_id),
            meeting_date="",
            plan=item.plan,
            conversation_history=item.conversation_history or [],
            attempt_count=item.attempt_count,
            max_attempts=item.max_attempts,
            error_context=item.result or "",
        )
    else:
        prompt = build_prompt(
            description=item.description,
            action_type=item.action_type,
            priority=item.priority,
            meeting_title=str(item.meeting_id),
            meeting_date="",
        )
```

**Step 6: Update allowed statuses in execute endpoint**

Change line 125:

```python
        if item.status not in ("pending", "awaiting_input", "failed", "awaiting_plan_review"):
```

**Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_execution.py
git commit -m "feat(tasks): Superpowers pipeline — clarify, plan, TDD execute, verify"
```

---

### Task 5: Update Answer Endpoint for Conversation History

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py:193-241`

**Step 1: Update the answer handler to store conversation history**

Replace the `awaiting_input` branch (lines 212-238):

```python
        if item.status == "awaiting_input":
            import asyncio
            from claude_executor import build_prompt, build_retry_prompt
            from models import TaskExecution
            from routes_execution import _run_execution, _RUNNING

            # Append admin answer to conversation history
            history = list(item.conversation_history or [])
            history.append({"role": "admin", "content": body.answer})
            item.conversation_history = history
            item.status = "running"
            new_exec = TaskExecution(task_id=item.id, status="running", log="")
            s.add(new_exec)
            await s.commit()
            await s.refresh(item)
            await s.refresh(new_exec)

            # Build prompt with full context
            if item.max_attempts > 1 and item.plan:
                prompt = build_retry_prompt(
                    description=item.description,
                    action_type=item.action_type,
                    priority=item.priority,
                    meeting_title=str(item.meeting_id),
                    meeting_date="",
                    plan=item.plan,
                    attempt_count=item.attempt_count,
                    max_attempts=item.max_attempts,
                    error_context="",
                    conversation_history=history,
                )
            else:
                prompt = (
                    build_prompt(
                        description=item.description,
                        action_type=item.action_type,
                        priority=item.priority,
                        meeting_title=str(item.meeting_id),
                        meeting_date="",
                    )
                    + f"\n\nADMIN PROVIDED THIS ANSWER: {body.answer}"
                )

            _RUNNING[item.id] = {"task": None, "proc": None}
            bg = asyncio.create_task(_run_execution(item.id, new_exec.id, prompt))
            _RUNNING[item.id]["task"] = bg
            return item
```

**Step 2: Update create_task to accept max_attempts**

In the `create_task` endpoint (line 121-128), add `max_attempts`:

```python
    item = TaskItem(
        meeting_id=uuid.uuid4(),
        action_type=body.action_type,
        assignee_name=assignee_name,
        assignee_email=assignee_email,
        description=body.description.strip()[:2000],
        priority=body.priority,
        status="pending",
        max_attempts=body.max_attempts,
    )
```

**Step 3: Update STATUS_BY_TAB for new statuses**

```python
STATUS_BY_TAB: dict[str, list[str]] = {
    "pending": ["pending", "awaiting_input", "planning", "awaiting_plan_review"],
    "progress": ["running", "claimed_manual"],
    "done": ["completed", "failed"],
}
```

**Step 4: Commit**

```bash
git add mcp-servers/tasks/routes_tasks.py
git commit -m "feat(tasks): conversation history in answer, max_attempts in create"
```

---

### Task 6: Preview API — File Tree + App Runner

**Files:**
- Create: `mcp-servers/tasks/app_runner.py`
- Create: `mcp-servers/tasks/routes_preview.py`

**Step 1: Write app_runner.py**

```python
"""Manage preview subprocesses for built apps."""
import asyncio
import logging
import os
import time

logger = logging.getLogger("tasks.preview")

WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
PREVIEW_PORT_START = 9100
IDLE_TIMEOUT = 1800  # 30 minutes

_current: dict | None = None  # {"slug": str, "port": int, "proc": Process, "started": float}


async def start_preview(slug: str) -> int:
    """Start serving an app. Kills any existing preview first. Returns port."""
    global _current
    await stop_preview()

    app_dir = os.path.join(WORKSPACE, "apps", slug)
    if not os.path.isdir(app_dir):
        raise FileNotFoundError(f"App directory not found: apps/{slug}/")

    port = PREVIEW_PORT_START
    pkg_json = os.path.join(app_dir, "package.json")

    if os.path.isfile(pkg_json):
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", f"cd {app_dir} && npm install --silent && npm run dev -- --port {port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            "npx", "serve", "-s", app_dir, "-l", str(port), "--no-clipboard",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    _current = {"slug": slug, "port": port, "proc": proc, "started": time.time()}
    logger.info("Preview started: %s on port %d (pid %d)", slug, port, proc.pid)
    return port


async def stop_preview() -> None:
    global _current
    if _current is None:
        return
    proc = _current["proc"]
    try:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass
    logger.info("Preview stopped: %s", _current["slug"])
    _current = None


def get_status() -> dict | None:
    if _current is None:
        return None
    elapsed = time.time() - _current["started"]
    return {
        "slug": _current["slug"],
        "port": _current["port"],
        "pid": _current["proc"].pid,
        "running": _current["proc"].returncode is None,
        "elapsed_seconds": int(elapsed),
    }
```

**Step 2: Write routes_preview.py**

```python
"""Preview API: file tree, file content, app runner."""
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app_runner import get_status, start_preview, stop_preview
from auth import AdminUser, current_admin
from db import session
from models import TaskItem

router = APIRouter(prefix="/api/tasks")

WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")


async def _get_build_task(task_id: UUID) -> TaskItem:
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not item.built_app_slug:
        raise HTTPException(status_code=404, detail="No built app for this task")
    return item


@router.get("/{task_id}/files")
async def list_files(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Return recursive file tree of the built app."""
    item = await _get_build_task(task_id)
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    if not app_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"App directory not found: apps/{item.built_app_slug}")
    files = []
    for p in sorted(app_dir.rglob("*")):
        if p.is_file() and "node_modules" not in p.parts:
            files.append({
                "path": str(p.relative_to(app_dir)),
                "size": p.stat().st_size,
            })
    return {"slug": item.built_app_slug, "files": files}


@router.get("/{task_id}/files/{file_path:path}")
async def read_file(task_id: UUID, file_path: str, user: AdminUser = Depends(current_admin)):
    """Read a single file from the built app."""
    item = await _get_build_task(task_id)
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    target = (app_dir / file_path).resolve()
    # Path traversal guard
    if not str(target).startswith(str(app_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.stat().st_size > 500_000:
        raise HTTPException(status_code=413, detail="File too large to preview")
    return {"path": file_path, "content": target.read_text(errors="replace")}


@router.post("/{task_id}/preview/start")
async def preview_start(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Start serving the built app for preview."""
    item = await _get_build_task(task_id)
    try:
        port = await start_preview(item.built_app_slug)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "started", "port": port, "slug": item.built_app_slug}


@router.post("/{task_id}/preview/stop")
async def preview_stop(task_id: UUID, user: AdminUser = Depends(current_admin)):
    await stop_preview()
    return {"status": "stopped"}


@router.get("/{task_id}/preview/status")
async def preview_status(task_id: UUID, user: AdminUser = Depends(current_admin)):
    status = get_status()
    return status or {"running": False}
```

**Step 3: Register the router in main.py**

Add to `main.py` (after line 12):

```python
from routes_preview import router as preview_router
```

And after line 29 (after `app.include_router(cron_router)`):

```python
app.include_router(preview_router)
```

**Step 4: Commit**

```bash
git add mcp-servers/tasks/app_runner.py mcp-servers/tasks/routes_preview.py mcp-servers/tasks/main.py
git commit -m "feat(tasks): preview API — file tree, file reader, app runner"
```

---

### Task 7: Frontend — Loop Mode UI in task-panel.js

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js`

**Step 1: Update renderPending() for loop mode tasks**

Add plan review UI for `awaiting_plan_review` status. In the `renderPending` function, add this block for plan review (after the `askInputUI` block):

```javascript
// Plan review UI for awaiting_plan_review tasks
const planReviewUI = t.status === "awaiting_plan_review" && t.plan
  ? `<div style="background:#0a1a1a;border:1px solid #065f46;border-radius:4px;padding:8px;font-size:11px;color:#6ee7b7;margin-bottom:8px;max-height:200px;overflow-y:auto;white-space:pre-wrap;"><strong>AI Plan:</strong><br/>${escapeHtml(t.plan)}</div>
     <div class="aiui-tp-actions">
       <button class="aiui-tp-btn-ai" data-task-action="approve-plan" data-task-id="${t.id}">✓ Approve Plan</button>
       <button class="aiui-tp-btn-manual" data-task-action="reject-plan" data-task-id="${t.id}">✗ Reject</button>
     </div>`
  : "";
```

**Step 2: Add attempt badge and loop indicator**

In the badges section of renderPending/renderProgress/renderDone, add:

```javascript
${t.max_attempts > 1 ? `<span class="aiui-tp-badge" style="background:#312e81;color:#c4b5fd;">🔄 Loop ${t.attempt_count}/${t.max_attempts}</span>` : ''}
```

**Step 3: Add action handlers for plan review**

In `onAction()`, add cases:

```javascript
else if (action === "approve-plan") {
    await api("POST", `/${id}/review-plan`, { approved: true });
    await refreshAll();
}
else if (action === "reject-plan") {
    showTextModal({
        title: "Reject Plan — Feedback (optional)",
        placeholder: "What should be different?",
        saveLabel: "Reject",
        allowEmpty: true,
        onSave: async (fb) => { await api("POST", `/${id}/review-plan`, { approved: false, feedback: fb }); await refreshAll(); },
    });
}
```

**Step 4: Add loop mode buttons — Clarify → Plan → AI flow**

In `renderPending`, update the `canAi` actions block to show the Superpowers pipeline:

```javascript
if (canAi) {
    let loopBtns = "";
    if (t.max_attempts > 1) {
        if (!t.plan && t.plan_status !== "approved") {
            // No plan yet — show Clarify (starts Q&A) and Plan (skips to plan)
            loopBtns = `<button class="aiui-tp-btn-ai" data-task-action="clarify" data-task-id="${t.id}" style="background:#7c3aed;">💬 Clarify</button>
                        <button class="aiui-tp-btn-ai" data-task-action="plan" data-task-id="${t.id}" style="background:#4f46e5;">📋 Plan</button>`;
        }
    }
    actions = `${loopBtns}
               <button class="aiui-tp-btn-ai" data-task-action="ai" data-task-id="${t.id}">⚡ AI</button>
               <button class="aiui-tp-btn-manual" data-task-action="manual" data-task-id="${t.id}">✋ Manual</button>
               <button class="aiui-tp-btn-manual" data-task-action="delete" data-task-id="${t.id}" title="Delete" style="flex:0 0 auto;padding:8px 10px;">🗑</button>`;
}
```

**Step 5: Add clarify + plan action handlers**

```javascript
else if (action === "clarify") {
    await api("POST", `/${id}/clarify`);
    await refreshAll();
    switchTab("progress");
    openStream(id);
}
else if (action === "plan") {
    await api("POST", `/${id}/plan`);
    await refreshAll();
    openStream(id);
}
```

**Step 6: Update create-task modal to include loop toggle**

In `showNewTaskModal` (or wherever the create-task form is), add a max_attempts selector:

```javascript
// Add inside the create task modal form HTML:
`<label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;color:#aaa;">
    <input type="checkbox" data-loop-toggle style="accent-color:#4f46e5;"/>
    Loop mode (plan → build → test → retry)
</label>`

// On save, read the toggle:
const loopToggle = modal.querySelector("[data-loop-toggle]");
const maxAttempts = loopToggle && loopToggle.checked ? 3 : 1;
// Include in API call:
await api("POST", "", { ...body, max_attempts: maxAttempts });
```

**Step 7: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks): loop mode UI — plan review, attempt badges, loop toggle"
```

---

### Task 8: Preview Page — static/preview.html

**Files:**
- Create: `mcp-servers/tasks/static/preview.html`

**Step 1: Write the preview page**

Create a self-contained HTML page with:
- Left sidebar: file tree (fetched from `/api/tasks/{id}/files`)
- Right pane: tabbed view (Code / Preview / Tests / Logs)
- Top bar: task title, Run/Stop buttons, status indicator
- Code tab: syntax highlighted via highlight.js CDN
- Preview tab: iframe pointing at `/tasks/preview-app/`
- Zero-dep vanilla JS (same approach as task-panel.js)
- Dark theme matching the existing panel aesthetic

The page reads `?task={id}` from URL params, fetches task data + files, and renders.

Key behaviors:
- Click file in tree → fetch content → show in Code tab with highlight.js
- Click "Run" → POST `/api/tasks/{id}/preview/start` → switch to Preview tab → load iframe
- Click "Stop" → POST `/api/tasks/{id}/preview/stop`
- Poll `/api/tasks/{id}/preview/status` every 5s to show running state
- Logs tab fetches from `/api/tasks/{id}/executions`
- Tests tab shows the test step output (parsed from execution log after `--- TEST STEP ---`)
- "← Back to Tasks" link returns to Open WebUI

Full HTML file will be ~400-600 lines. Write it as a complete standalone file.

**Step 2: Verify the file is served**

Run: `curl -s http://localhost:8210/tasks/static/preview.html | head -5`
Expected: HTML doctype and opening tags

**Step 3: Commit**

```bash
git add mcp-servers/tasks/static/preview.html
git commit -m "feat(tasks): preview page — file tree, code viewer, iframe runner"
```

---

### Task 9: Preview Button in task-panel.js

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js`

**Step 1: Add Preview App button to completed BUILD tasks**

In `renderDone()`, after the "View full AI log" button, add:

```javascript
const previewBtn = (t.action_type === "BUILD" && t.built_app_slug)
    ? `<a href="/tasks/static/preview.html?task=${t.id}" target="_blank"
         class="aiui-tp-btn-ai" style="text-decoration:none;text-align:center;display:inline-block;">
         🔍 Preview App</a>`
    : "";
```

Include `${previewBtn}` in the actions div alongside the existing buttons.

**Step 2: Show conversation history in awaiting_input tasks**

Update the `askInputUI` block in `renderPending()` to show prior Q&A:

```javascript
const historyHtml = (t.conversation_history || []).length > 0
    ? `<div style="max-height:120px;overflow-y:auto;margin-bottom:6px;">${
        t.conversation_history.map(h =>
            `<div style="font-size:11px;padding:4px 6px;margin:2px 0;border-radius:3px;background:${
                h.role === 'ai' ? '#1a1208' : '#0a1a14'};color:${
                h.role === 'ai' ? '#fcd34d' : '#86efac'};">
                <strong>${h.role === 'ai' ? 'AI' : 'You'}:</strong> ${escapeHtml(h.content)}
            </div>`
        ).join("")
    }</div>`
    : "";
```

Insert `${historyHtml}` before the textarea in the `askInputUI` block.

**Step 3: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js
git commit -m "feat(tasks): preview button on BUILD tasks + conversation history display"
```

---

### Task 10: Caddy Routing for Preview

**Files:**
- Modify: `Caddyfile`

**Step 1: Add preview-app proxy rule**

After the existing tasks static route (around line 128), add:

```caddyfile
# Preview app — proxies to the running app inside the tasks container
handle /tasks/preview-app/* {
    uri strip_prefix /tasks/preview-app
    reverse_proxy tasks:9100
}
```

**Step 2: Expose port 9100 in docker-compose.unified.yml**

In the `tasks` service definition, add port 9100 to the internal network (no host mapping needed — Caddy proxies internally):

```yaml
# No change needed — Docker Compose services can reach each other by name:port
# Caddy already has access to tasks:9100 on the internal network
```

Verify the tasks service doesn't need an explicit `expose: [9100]` — Docker Compose services can already reach each other on any port within the same network.

**Step 3: Commit**

```bash
git add Caddyfile
git commit -m "feat(caddy): add preview-app proxy route for built app previews"
```

---

### Task 11: Integration Smoke Test

**Step 1: Create a test task via the panel**

Open AIUI → Task Panel → "+" → Create task:
- Description: "Build a simple counter app: button to increment, button to decrement, displays the current count"
- Type: BUILD
- Priority: NICE_TO_HAVE
- Loop mode: ON (checkbox checked)

**Step 2: Run the plan step**

Click "📋 Plan" → watch SSE stream → verify plan appears → click "✓ Approve Plan"

**Step 3: Execute the build**

Click "⚡ AI" → watch execution → verify it completes (or retries if tests fail)

**Step 4: Preview the result**

Click "🔍 Preview App" → verify preview page loads → file tree shows files → click "Run" → verify iframe shows the counter app

**Step 5: Test NEEDS_INPUT flow**

Create a vague task: "Build me something to organize my work"
- Execute → expect NEEDS_INPUT → reply "Web app, React, todo list with categories"
- Verify conversation history shows in the panel
- Verify execution resumes with full context

---

### Task 12: Deploy to Hetzner

**Step 1: SCP changed files**

```bash
scp mcp-servers/tasks/migrations/002_loop_and_preview.sql root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/migrations/
scp mcp-servers/tasks/models.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/schemas.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/claude_executor.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/routes_execution.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/routes_tasks.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/routes_preview.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/app_runner.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/main.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/static/task-panel.js root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/
scp mcp-servers/tasks/static/preview.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/
scp Caddyfile root@46.224.193.25:/root/proxy-server/
```

**Step 2: Rebuild and restart**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks caddy"
```

**Step 3: Verify**

```bash
ssh root@46.224.193.25 "docker logs proxy-server-tasks-1 --tail 20"
# Expected: "DB initialized" — migration ran successfully
```
