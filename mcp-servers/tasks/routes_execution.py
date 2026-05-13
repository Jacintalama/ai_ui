"""AI execution: spawns the claude CLI subprocess, streams progress via SSE."""
import asyncio
import logging
import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sse_starlette.sse import EventSourceResponse

from agent_executor import get_executor
from auth import AdminUser, current_admin
from claude_executor import (
    build_prompt, build_clarify_prompt, build_plan_prompt,
    build_tdd_execute_prompt, build_verify_prompt,
    extract_app_slug, parse_outcome, parse_clarify_done,
    parse_plan, parse_test_outcome,
)
from db import session
from models import ChatMessage, ProjectSupabase, TaskExecution, TaskItem
from schemas import PlanReviewRequest, TaskOut


async def _lookup_supabase_url(s, slug: str | None) -> str | None:
    """Return Supabase URL configured for a project slug, or None."""
    if not slug:
        return None
    row = (await s.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == slug)
    )).scalar_one_or_none()
    return row.supabase_url if row else None


async def _lookup_supabase_config(s, slug: str | None) -> tuple[str | None, bool]:
    """Return (supabase_url, has_db_uri) for a project slug.

    has_db_uri is True iff the row has a non-empty db_uri_encrypted value —
    signals to prompt builders that the SQL-execute tool is available.
    """
    if not slug:
        return None, False
    row = (await s.execute(
        select(ProjectSupabase).where(ProjectSupabase.slug == slug)
    )).scalar_one_or_none()
    if not row:
        return None, False
    return row.supabase_url, bool(row.db_uri_encrypted)

logger = logging.getLogger("tasks")
router = APIRouter(prefix="/api/tasks")

# In-process registry of running execution tasks for cancellation.
# Each entry holds the asyncio task + the executor instance that owns the
# in-flight agent run. Cancel awaits executor.stop() to kill the underlying
# process (local subprocess or remote SSH session).
_RUNNING: dict[UUID, dict] = {}

TEAM_EMAIL = "team@aiui.local"


async def _stream_claude(prompt: str, execution_id: UUID, task_id: UUID) -> str:
    """Run a claude run via the configured executor; stream output to the
    execution log; return the full log as a string.

    AGENT_BACKEND env (read inside get_executor) decides whether this hits
    a local subprocess or a remote VM. The orchestrator behavior is
    identical either way — same sentinel stream, same log shape.
    """
    full_log: list[str] = []
    executor = get_executor()
    # Preserve any prior bookkeeping (e.g. the asyncio Task handle stashed
    # by /execute before the background coro started) and add the executor.
    entry = _RUNNING.setdefault(task_id, {})
    entry["executor"] = executor

    # Look up the slug for this task (RemoteExecutor needs it for workspace
    # keying; LocalExecutor ignores it).
    async with session() as s:
        task = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        slug = (task.built_app_slug if task else None) or None

    # If we're on the remote backend, record which agent host is handling
    # this execution. Guarded with try/except because the `agent_host`
    # column is not added until Task 9's migration — until then the UPDATE
    # raises ProgrammingError ("column ... does not exist"). The guard is
    # forward-compat only and should be removed once the migration lands.
    if executor.__class__.__name__ == "RemoteExecutor":
        agent_host_value = os.environ.get("AGENT_HOST")
        try:
            async with session() as s:
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == execution_id)
                    .values(agent_host=agent_host_value)
                )
                await s.commit()
        except Exception as exc:  # noqa: BLE001  pragma: no cover
            # Swallow column-missing errors so RemoteExecutor still streams
            # successfully before the Task 9 migration lands (which adds the
            # `agent_host` column). Any other DB error gets logged but does
            # not break the run. Remove this guard once the migration is in.
            logger.warning(
                "agent_host writeback skipped (likely missing column): %s", exc
            )

    try:
        async for chunk in executor.run(
            prompt, slug=slug, execution_id=str(execution_id)
        ):
            full_log.append(chunk)
            async with session() as s:
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == execution_id)
                    .values(log=TaskExecution.log + chunk)
                )
                await s.commit()
    finally:
        # Clear the executor handle but keep the rest of the entry — the
        # outer _run_execution finally block pops the whole entry.
        cur = _RUNNING.get(task_id)
        if cur is not None and cur.get("executor") is executor:
            cur.pop("executor", None)

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

        async with session() as s:
            task = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one()
            is_loop = task.max_attempts > 1
            attempt = task.attempt_count
            max_att = task.max_attempts
            supabase_url, has_db_uri = await _lookup_supabase_config(s, task.built_app_slug)
            assignee_email = task.assignee_email or ""
            built_slug = task.built_app_slug or ""

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
                supabase_url=supabase_url,
                has_db_uri=has_db_uri,
                slug=built_slug,
                user_email=assignee_email,
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
                    supabase_url=supabase_url,
                    has_db_uri=has_db_uri,
                    slug=built_slug,
                    user_email=assignee_email,
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

        history_update = {}
        if outcome.kind == "needs_input":
            history = list(task.conversation_history or [])
            history.append({"role": "ai", "content": outcome.payload, "attempt": attempt})
            history_update = {"conversation_history": history}

        # Only write built_app_slug when we actually extracted one from this
        # execution's output. Otherwise preserve whatever was set at task
        # creation (e.g. enhancement tasks inherit the slug from their source,
        # and Claude's completion message for a tweak rarely repeats the
        # `apps/<slug>/` path — without this guard the slug gets clobbered to
        # NULL, breaking the Preview App button and sidebar polling).
        update_values = {
            "status": new_task_status,
            "mode": mode_val,
            "result": outcome.payload,
            "completed_at": datetime.utcnow() if outcome.kind == "completed" else None,
            **history_update,
        }
        if slug:
            update_values["built_app_slug"] = slug

        async with session() as s:
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == execution_id)
                .values(status=new_exec_status, finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == task_id).values(**update_values)
            )
            # Auto-add the creator as owner of this project (idempotent).
            if slug:
                await s.execute(
                    text(
                        "INSERT INTO tasks.project_members (slug, user_email, role, added_by) "
                        "SELECT :slug, assignee_email, 'owner', assignee_email "
                        "FROM tasks.items WHERE id = :task_id AND assignee_email IS NOT NULL "
                        "ON CONFLICT (slug, user_email) DO NOTHING"
                    ),
                    {"slug": slug, "task_id": task_id},
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


def _build_execute_prompt(
    item: TaskItem,
    supabase_url: str | None,
    has_db_uri: bool,
) -> str:
    """Compose the right execute-style prompt for an item that's about to
    transition into `running`. Shared by /execute and /resume.
    """
    item_slug = item.built_app_slug or ""
    item_email = item.assignee_email or ""
    if item.max_attempts > 1 and item.plan and item.plan_status == "approved":
        return build_tdd_execute_prompt(
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
            supabase_url=supabase_url,
            has_db_uri=has_db_uri,
            slug=item_slug,
            user_email=item_email,
        )
    return build_prompt(
        description=item.description,
        action_type=item.action_type,
        priority=item.priority,
        meeting_title=str(item.meeting_id),
        meeting_date="",
        supabase_url=supabase_url,
        has_db_uri=has_db_uri,
        slug=item_slug,
        user_email=item_email,
    )


@router.post("/{task_id}/execute", response_model=TaskOut)
async def execute(task_id: UUID, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        item = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.status == "awaiting_supabase":
            raise HTTPException(
                status_code=409,
                detail="Connect Supabase first or skip",
            )
        if item.built_app_slug:
            from routes_projects import _require_role
            await _require_role(s, item.built_app_slug, user.email, "editor",
                                is_admin=user.is_admin)
        elif item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
        if item.action_type not in ("BUILD", "INTEGRATE", "RESEARCH"):
            raise HTTPException(status_code=400, detail="AI execution not allowed for this task type")

        # Serialize check+insert per slug so two parallel /execute calls
        # can't both transition the same task from pending to running.
        # Falls back to per-task-id lock when there's no slug yet.
        lock_key = f"build:{item.built_app_slug}" if item.built_app_slug else f"task:{item.id}"
        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": lock_key},
        )
        # Re-read status under the lock — another writer may have just changed it.
        await s.refresh(item)
        if item.status not in ("pending", "awaiting_input", "failed", "awaiting_plan_review"):
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")

        # Reap any orphan 'running' executions for this task so the partial
        # unique index doesn't block the new row.
        await s.execute(
            update(TaskExecution)
            .where(TaskExecution.task_id == item.id, TaskExecution.status == "running")
            .values(status="failed", error="orphan execution — reaped on retry", finished_at=datetime.utcnow())
        )

        item.status = "running"
        item.mode = "ai"
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)
        supabase_url, has_db_uri = await _lookup_supabase_config(s, item.built_app_slug)

    prompt = _build_execute_prompt(item, supabase_url, has_db_uri)
    # Create a holder dict that _stream_claude will fill with the executor
    # instance so cancel can call executor.stop().
    _RUNNING[item.id] = {"task": None}
    bg = asyncio.create_task(_run_execution(item.id, execution.id, prompt))
    _RUNNING[item.id]["task"] = bg
    return item


class ResumeRequest(BaseModel):
    skip: bool = False


@router.post("/{task_id}/resume", response_model=TaskOut)
async def resume(
    task_id: UUID,
    body: ResumeRequest,
    user: AdminUser = Depends(current_admin),
):
    """Resume a build that's been gated waiting for Supabase.

    Two paths:
    - `skip=False` (default): verify Supabase is now linked for the project's
      slug. If yes, transition to `pending`/`running` and kick off the build.
      If not, 412 — the user needs to finish the connect popup first.
    - `skip=True`: append a localStorage-only marker to the description and
      build a frontend-only version.

    Either way, an assistant chat message is appended so the chat UI reflects
    what just happened.
    """
    async with session() as s:
        item = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.built_app_slug:
            from routes_projects import _require_role
            await _require_role(s, item.built_app_slug, user.email, "editor",
                                is_admin=user.is_admin)
        elif item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
        if item.status != "awaiting_supabase":
            raise HTTPException(
                status_code=409,
                detail="Task is not awaiting Supabase",
            )

        if body.skip:
            new_desc = (item.description or "") + (
                "\n\nNOTE: User chose to build WITHOUT a backend. "
                "Use localStorage only."
            )
            item.description = new_desc[:20_000]
            chat_text = "Building frontend-only version…"
        else:
            # Verify Supabase is actually linked for this slug.
            supa_row = None
            if item.built_app_slug:
                supa_row = (await s.execute(
                    select(ProjectSupabase).where(
                        ProjectSupabase.slug == item.built_app_slug
                    )
                )).scalar_one_or_none()
            linked = bool(
                supa_row
                and (supa_row.linked_project_ref or supa_row.supabase_url)
            )
            if not linked:
                raise HTTPException(
                    status_code=412,
                    detail="Supabase still not linked",
                )
            chat_text = "Supabase connected ✓ — building now…"

        item.status = "running"
        item.mode = "ai"
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution)
        if item.built_app_slug:
            s.add(ChatMessage(
                slug=item.built_app_slug,
                user_email=user.email,
                role="assistant",
                content=chat_text,
            ))
        await s.commit()
        await s.refresh(item)
        await s.refresh(execution)
        supabase_url, has_db_uri = await _lookup_supabase_config(s, item.built_app_slug)

    prompt = _build_execute_prompt(item, supabase_url, has_db_uri)
    _RUNNING[item.id] = {"task": None}
    bg = asyncio.create_task(_run_execution(item.id, execution.id, prompt))
    _RUNNING[item.id]["task"] = bg
    return item


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


@router.post("/{task_id}/clarify", response_model=TaskOut)
async def start_clarify(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Start the CLARIFY phase — Claude asks structured questions before planning."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.built_app_slug:
            from routes_projects import _require_role
            await _require_role(s, item.built_app_slug, user.email, "editor",
                                is_admin=user.is_admin)
        elif item.assignee_email not in (user.email, TEAM_EMAIL):
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
    _RUNNING[item.id] = {"task": None}

    async def _clarify_bg(tid, eid, p):
        try:
            full_output = await _stream_claude(p, eid, tid)
            done_text = parse_clarify_done(full_output)
            outcome = parse_outcome(full_output)

            async with session() as s:
                task = (await s.execute(select(TaskItem).where(TaskItem.id == tid))).scalar_one()
                history = list(task.conversation_history or [])

                if done_text:
                    await s.execute(
                        update(TaskExecution).where(TaskExecution.id == eid)
                        .values(status="succeeded", finished_at=datetime.utcnow())
                    )
                    await s.execute(
                        update(TaskItem).where(TaskItem.id == tid).values(
                            status="planning", result=done_text,
                        )
                    )
                    await s.commit()

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
                    history.append({"role": "ai", "content": outcome.payload, "attempt": 0})
                    await s.execute(
                        update(TaskExecution).where(TaskExecution.id == eid)
                        .values(status="needs_input", finished_at=datetime.utcnow())
                    )
                    await s.execute(
                        update(TaskItem).where(TaskItem.id == tid).values(
                            status="awaiting_input", result=outcome.payload,
                            conversation_history=history,
                        )
                    )
                    await s.commit()
                else:
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


@router.post("/{task_id}/plan", response_model=TaskOut)
async def start_plan(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Manually trigger the PLAN phase (can skip CLARIFY if task is clear)."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.built_app_slug:
            from routes_projects import _require_role
            await _require_role(s, item.built_app_slug, user.email, "editor",
                                is_admin=user.is_admin)
        elif item.assignee_email not in (user.email, TEAM_EMAIL):
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

    requirements = item.result or ""
    prompt = build_plan_prompt(
        description=item.description,
        action_type=item.action_type,
        priority=item.priority,
        requirements=requirements,
    )
    _RUNNING[item.id] = {"task": None}
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
            item.status = "pending"
        else:
            item.plan_status = "rejected"
            item.status = "pending"
            item.plan = None
            if body.feedback:
                item.result = f"Plan rejected: {body.feedback}"
        await s.commit()
        await s.refresh(item)
    return item


@router.get("/{task_id}/stream")
async def stream(
    task_id: UUID,
    request: Request,
    from_: int = 0,
    user: AdminUser = Depends(current_admin),
):
    """SSE stream of execution log. Pass `?from_=<line_no>` to resume after disconnect."""

    async def event_generator():
        last_len = from_
        while True:
            if await request.is_disconnected():
                break
            async with session() as s:
                row = (
                    await s.execute(
                        select(TaskExecution)
                        .where(TaskExecution.task_id == task_id)
                        .order_by(TaskExecution.started_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                item = (
                    await s.execute(select(TaskItem).where(TaskItem.id == task_id))
                ).scalar_one_or_none()
            if row is None or item is None:
                yield {"event": "error", "data": "no execution"}
                break
            if len(row.log) > last_len:
                yield {"event": "log", "data": row.log[last_len:]}
                last_len = len(row.log)
            if item.status != "running":
                yield {"event": "done", "data": item.status}
                break
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_generator())


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel(task_id: UUID, user: AdminUser = Depends(current_admin)):
    entry = _RUNNING.pop(task_id, None)
    if entry:
        executor = entry.get("executor")
        if executor is not None:
            try:
                await executor.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("executor.stop() raised on cancel: %s", exc)
        task = entry.get("task")
        if task is not None:
            task.cancel()
    async with session() as s:
        # Put the task back to pending so admin can retry / manual-claim.
        await s.execute(
            update(TaskItem).where(TaskItem.id == task_id).values(status="pending", mode=None)
        )
        await s.execute(
            update(TaskExecution)
            .where(TaskExecution.task_id == task_id, TaskExecution.status == "running")
            .values(status="failed", error="cancelled by user", finished_at=datetime.utcnow())
        )
        await s.commit()
        item = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one()
    return item
