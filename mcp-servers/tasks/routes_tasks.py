"""Task CRUD + state transitions (manual mode)."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from auth import AdminUser, current_admin
from db import session
from models import TaskItem
from schemas import AnswerRequest, CompleteRequest, TaskOut

router = APIRouter(prefix="/api/tasks")

TEAM_EMAIL = "team@aiui.local"

STATUS_BY_TAB: dict[str, list[str]] = {
    "pending": ["pending", "awaiting_input"],
    "progress": ["running", "claimed_manual"],
    "done": ["completed", "failed"],
}


async def _get_owned_task(s, task_id: UUID, email: str) -> TaskItem:
    res = await s.execute(select(TaskItem).where(TaskItem.id == task_id))
    item = res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if item.assignee_email != email and item.assignee_email != TEAM_EMAIL:
        raise HTTPException(status_code=403, detail="Not your task")
    return item


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status: str = "pending",
    limit: int = 50,
    user: AdminUser = Depends(current_admin),
):
    if status not in STATUS_BY_TAB:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    async with session() as s:
        q = (
            select(TaskItem)
            .where(
                TaskItem.assignee_email.in_([user.email, TEAM_EMAIL]),
                TaskItem.status.in_(STATUS_BY_TAB[status]),
            )
            .order_by(TaskItem.created_at.desc())
            .limit(limit)
        )
        rows = (await s.execute(q)).scalars().all()
    return rows


@router.get("/{task_id}/executions")
async def list_executions(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Return execution history for a task — used by the panel to show what AI did."""
    from models import TaskExecution
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        rows = (await s.execute(
            select(TaskExecution)
            .where(TaskExecution.task_id == item.id)
            .order_by(TaskExecution.started_at.desc())
        )).scalars().all()
        return [
            {
                "id": str(r.id),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "log": r.log or "",
                "error": r.error,
            }
            for r in rows
        ]


@router.get("/history", response_model=list[TaskOut])
async def history(
    limit: int = 50,
    offset: int = 0,
    user: AdminUser = Depends(current_admin),
):
    async with session() as s:
        q = (
            select(TaskItem)
            .where(
                TaskItem.assignee_email.in_([user.email, TEAM_EMAIL]),
                TaskItem.status.in_(["completed", "failed"]),
            )
            .order_by(TaskItem.completed_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        rows = (await s.execute(q)).scalars().all()
    return rows


@router.post("/{task_id}/manual", response_model=TaskOut)
async def claim_manual(task_id: UUID, user: AdminUser = Depends(current_admin)):
    """Claim a task for manual handling.

    Allowed from 'pending' (fresh task) or 'failed' (admin taking over after
    an AI execution failure). 'failed -> claimed_manual' preserves the
    execution log for audit and lets the admin finish the work.
    """
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status not in ("pending", "failed"):
            raise HTTPException(status_code=409, detail=f"Task is {item.status}")
        item.status = "claimed_manual"
        item.mode = "manual"
        item.completed_at = None  # reset in case we're reviving a failed task
        await s.commit()
        await s.refresh(item)
    return item


@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete(
    task_id: UUID,
    body: CompleteRequest,
    user: AdminUser = Depends(current_admin),
):
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status not in ("claimed_manual", "awaiting_input"):
            raise HTTPException(status_code=409, detail=f"Cannot complete from {item.status}")
        item.status = "completed"
        item.result = body.result
        item.completed_at = datetime.utcnow()
        await s.commit()
        await s.refresh(item)
    return item


@router.post("/{task_id}/answer", response_model=TaskOut)
async def answer(
    task_id: UUID,
    body: AnswerRequest,
    user: AdminUser = Depends(current_admin),
):
    """For ASK_USER tasks, completes immediately. For awaiting_input AI tasks, resumes execution."""
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)

        if item.action_type == "ASK_USER" and item.status == "pending":
            item.status = "completed"
            item.mode = "manual"
            item.result = body.answer
            item.completed_at = datetime.utcnow()
            await s.commit()
            await s.refresh(item)
            return item

        if item.status == "awaiting_input":
            # Resume AI execution with the admin's answer appended to context.
            # Imported lazily to avoid circular import with routes_execution.
            import asyncio

            from claude_executor import build_prompt
            from models import TaskExecution
            from routes_execution import _run_execution

            item.status = "running"
            new_exec = TaskExecution(task_id=item.id, status="running", log="")
            s.add(new_exec)
            await s.commit()
            await s.refresh(item)
            await s.refresh(new_exec)

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
            asyncio.create_task(_run_execution(item.id, new_exec.id, prompt))
            return item

        raise HTTPException(status_code=409, detail="Answer not applicable in current state")
