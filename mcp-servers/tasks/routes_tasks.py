"""Task CRUD + state transitions (manual mode)."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

import uuid

from assignee_map import TEAM_EMAIL as TEAM_EMAIL_CONST, AssigneeMap
from auth import AdminUser, current_admin
from db import session
from models import TaskItem
from schemas import AnswerRequest, CompleteRequest, CreateTaskRequest, EnhanceRequest, TaskOut

router = APIRouter(prefix="/api/tasks")

TEAM_EMAIL = "team@aiui.local"

STATUS_BY_TAB: dict[str, list[str]] = {
    "pending": ["pending", "awaiting_input", "planning", "awaiting_plan_review"],
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


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(body: CreateTaskRequest, user: AdminUser = Depends(current_admin)):
    """Admin-created task from the panel. Not tied to a real meeting —
    uses a synthetic meeting_id so it shows up as normal in the panel."""
    amap = AssigneeMap.from_env()
    assignee_raw = (body.assignee or "self").strip()
    if assignee_raw.lower() == "self":
        assignee_name = user.email.split("@")[0]
        assignee_email = user.email
    elif assignee_raw.lower() == "team":
        assignee_name = "team"
        assignee_email = TEAM_EMAIL_CONST
    else:
        assignee_name = assignee_raw
        assignee_email = amap.resolve(assignee_raw)

    item = TaskItem(
        meeting_id=uuid.uuid4(),  # synthetic — no real meeting
        action_type=body.action_type,
        assignee_name=assignee_name,
        assignee_email=assignee_email,
        description=body.description.strip()[:2000],
        priority=body.priority,
        status="pending",
        max_attempts=body.max_attempts,
    )
    async with session() as s:
        s.add(item)
        await s.commit()
        await s.refresh(item)
    return item


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id, user: AdminUser = Depends(current_admin)):
    """Delete a task — only allowed from 'pending' status and for tasks
    owned by the current admin (or in the shared team bucket)."""
    from uuid import UUID
    try:
        tid = UUID(str(task_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")
    async with session() as s:
        item = await _get_owned_task(s, tid, user.email)
        if item.status != "pending":
            raise HTTPException(status_code=409, detail=f"Can only delete pending tasks (this is {item.status})")
        await s.delete(item)
        await s.commit()
    return None


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
            import asyncio
            from claude_executor import build_prompt, build_tdd_execute_prompt
            from models import TaskExecution
            from routes_execution import _run_execution, _RUNNING

            history = list(item.conversation_history or [])
            history.append({"role": "admin", "content": body.answer})
            item.conversation_history = history
            item.status = "running"
            new_exec = TaskExecution(task_id=item.id, status="running", log="")
            s.add(new_exec)
            await s.commit()
            await s.refresh(item)
            await s.refresh(new_exec)

            if item.max_attempts > 1 and item.plan:
                prompt = build_tdd_execute_prompt(
                    description=item.description,
                    action_type=item.action_type,
                    priority=item.priority,
                    meeting_title=str(item.meeting_id),
                    meeting_date="",
                    plan=item.plan,
                    conversation_history=history,
                    attempt_count=item.attempt_count,
                    max_attempts=item.max_attempts,
                    error_context="",
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

        raise HTTPException(status_code=409, detail="Answer not applicable in current state")


@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(
    body: EnhanceRequest,
    user: AdminUser = Depends(current_admin),
):
    """Create a new BUILD task that modifies an existing app.

    Skips CLARIFY/PLAN (plan_status='approved' set up front) and goes straight
    to TDD EXECUTE with ENHANCE_PROMPT_TEMPLATE so the user gets a fast
    iteration loop — type change -> AI edits existing files -> preview reloads.
    """
    import asyncio
    from claude_executor import build_enhance_prompt
    from models import TaskExecution
    from routes_execution import _run_execution, _RUNNING

    async with session() as s:
        # 1. Validate source
        source = (await s.execute(
            select(TaskItem).where(TaskItem.id == body.source_task_id)
        )).scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=404, detail="Source task not found")
        if source.action_type != "BUILD":
            raise HTTPException(status_code=400, detail="Can only enhance BUILD tasks")
        if not source.built_app_slug:
            raise HTTPException(
                status_code=400,
                detail="Source task has no built_app_slug — nothing to enhance",
            )

        # 2. Reject concurrent enhancements on same app
        in_flight = (await s.execute(
            select(TaskItem).where(
                TaskItem.built_app_slug == source.built_app_slug,
                TaskItem.status.in_(["running", "planning", "awaiting_input"]),
            )
        )).scalar_one_or_none()
        if in_flight:
            raise HTTPException(
                status_code=409,
                detail=f"Another enhancement is already in progress for apps/{source.built_app_slug}/",
            )

        # 3. Create new enhancement task
        new_task = TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name=user.email.split("@")[0],
            assignee_email=user.email,
            description=f"Enhance apps/{source.built_app_slug}/: {body.prompt.strip()[:400]}",
            priority="NICE_TO_HAVE",
            status="running",
            mode="ai",
            max_attempts=max(source.max_attempts or 1, 1),
            built_app_slug=source.built_app_slug,
            plan_status="approved",
        )
        s.add(new_task)
        await s.commit()
        await s.refresh(new_task)

        execution = TaskExecution(task_id=new_task.id, status="running", log="")
        s.add(execution)
        await s.commit()
        await s.refresh(execution)

    # 4. Fire background execution with ENHANCE prompt
    prompt = build_enhance_prompt(
        slug=source.built_app_slug,
        user_request=body.prompt.strip(),
        attempt_count=0,
        max_attempts=new_task.max_attempts,
    )
    _RUNNING[new_task.id] = {"task": None, "proc": None}
    bg = asyncio.create_task(_run_execution(new_task.id, execution.id, prompt))
    _RUNNING[new_task.id]["task"] = bg

    return new_task
