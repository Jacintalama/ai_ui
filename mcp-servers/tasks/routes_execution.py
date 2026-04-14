"""AI execution: spawns the claude CLI subprocess, streams progress via SSE."""
import asyncio
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sse_starlette.sse import EventSourceResponse

from auth import AdminUser, current_admin
from claude_executor import build_prompt, parse_outcome, run_claude_subprocess
from db import session
from models import TaskExecution, TaskItem
from schemas import TaskOut

logger = logging.getLogger("tasks")
router = APIRouter(prefix="/api/tasks")

# In-process registry of running execution tasks for cancellation
_RUNNING: dict[UUID, asyncio.Task] = {}

TEAM_EMAIL = "team@aiui.local"


async def _run_execution(task_id: UUID, execution_id: UUID, prompt: str):
    """Background coroutine: stream Claude output, parse outcome, persist."""
    full_log: list[str] = []
    try:
        async for chunk in run_claude_subprocess(prompt):
            full_log.append(chunk)
            async with session() as s:
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == execution_id)
                    .values(log=TaskExecution.log + chunk)
                )
                await s.commit()

        outcome = parse_outcome("".join(full_log))
        new_task_status = {
            "completed": "completed",
            "needs_input": "awaiting_input",
            "needs_steps": "claimed_manual",
            "failed": "failed",
        }[outcome.kind]
        new_exec_status = {
            "completed": "succeeded",
            "needs_input": "needs_input",
            "needs_steps": "succeeded",
            "failed": "failed",
        }[outcome.kind]

        async with session() as s:
            await s.execute(
                update(TaskExecution)
                .where(TaskExecution.id == execution_id)
                .values(status=new_exec_status, finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem)
                .where(TaskItem.id == task_id)
                .values(
                    status=new_task_status,
                    mode="ai" if outcome.kind != "needs_steps" else "manual",
                    result=outcome.payload,
                    completed_at=datetime.utcnow() if outcome.kind == "completed" else None,
                )
            )
            await s.commit()
    except Exception as exc:
        logger.exception("Execution failed: %s", exc)
        async with session() as s:
            await s.execute(
                update(TaskExecution)
                .where(TaskExecution.id == execution_id)
                .values(status="failed", error=str(exc), finished_at=datetime.utcnow())
            )
            await s.execute(
                update(TaskItem).where(TaskItem.id == task_id).values(status="failed")
            )
            await s.commit()
    finally:
        _RUNNING.pop(task_id, None)


@router.post("/{task_id}/execute", response_model=TaskOut)
async def execute(task_id: UUID, user: AdminUser = Depends(current_admin)):
    async with session() as s:
        item = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if item.assignee_email not in (user.email, TEAM_EMAIL):
            raise HTTPException(status_code=403, detail="Not your task")
        if item.action_type not in ("BUILD", "INTEGRATE"):
            raise HTTPException(status_code=400, detail="AI execution not allowed for this task type")
        if item.status not in ("pending", "awaiting_input", "failed"):
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

    prompt = build_prompt(
        description=item.description,
        action_type=item.action_type,
        priority=item.priority,
        meeting_title=str(item.meeting_id),
        meeting_date="",
    )
    bg = asyncio.create_task(_run_execution(item.id, execution.id, prompt))
    _RUNNING[item.id] = bg
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
    bg = _RUNNING.pop(task_id, None)
    if bg:
        bg.cancel()
    async with session() as s:
        await s.execute(
            update(TaskItem).where(TaskItem.id == task_id).values(status="failed")
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
