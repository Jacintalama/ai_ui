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
from schemas import AnswerRequest, ChatRequest, ChatResponse, CompleteRequest, CreateTaskRequest, EnhanceRequest, TaskOut

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
    slug: str | None = None,
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
        if slug:
            q = q.where(TaskItem.built_app_slug == slug)
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
            from claude_executor import build_prompt, build_tdd_execute_prompt, build_enhance_prompt
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

            # Enhance tasks need `build_enhance_prompt` so Claude stays in the
            # app's existing stack/dir and follows the enhance rules. Using the
            # generic `build_prompt` here would make Claude start a NEW app
            # instead of modifying `apps/<slug>/`.
            is_enhance = (
                item.action_type == "BUILD"
                and item.built_app_slug
                and (item.description or "").startswith("Enhance apps/")
            )

            if is_enhance:
                convo_block_lines = []
                for entry in history:
                    role = entry.get("role", "")
                    content = entry.get("content", "")
                    if role == "ai":
                        convo_block_lines.append(f"AI asked: {content}")
                    elif role == "admin":
                        convo_block_lines.append(f"ADMIN answered: {content}")
                convo_block = "\n".join(convo_block_lines)
                # Strip the "Enhance apps/<slug>/: " prefix to get the raw ask,
                # then append the clarifying round so Claude has full context.
                raw_ask = (item.description or "").split(":", 1)[-1].strip()
                user_request = (
                    raw_ask
                    + "\n\nCONVERSATION WITH ADMIN:\n"
                    + convo_block
                )
                prompt = build_enhance_prompt(
                    slug=item.built_app_slug,
                    user_request=user_request,
                    attempt_count=item.attempt_count,
                    max_attempts=item.max_attempts,
                )
            elif item.max_attempts > 1 and item.plan:
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


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: UUID,
    user: AdminUser = Depends(current_admin),
):
    """Cancel a task stuck in a non-terminal state.

    Unblocks the admin when an enhancement is stuck in `awaiting_input`
    (AI asked a clarifying question nobody answered) or `running` (crashed
    background worker) and is preventing new enhancements on the same slug
    from being queued (see `/enhance` 409 path).

    The DB row is marked `failed` with a 'Cancelled by user' result. If a
    background task is still tracked in `_RUNNING`, its asyncio.Task and
    subprocess are also cancelled so they stop consuming resources.
    """
    TERMINAL = {"completed", "failed"}
    async with session() as s:
        item = await _get_owned_task(s, task_id, user.email)
        if item.status in TERMINAL:
            raise HTTPException(
                status_code=409,
                detail=f"Task already {item.status}; nothing to cancel",
            )
        item.status = "failed"
        item.result = "Cancelled by user"
        item.updated_at = datetime.utcnow()
        await s.commit()
        await s.refresh(item)

    # Best-effort: cancel any in-flight asyncio task + child process
    from routes_execution import _RUNNING
    entry = _RUNNING.pop(task_id, None)
    if entry:
        bg_task = entry.get("task")
        if bg_task and not bg_task.done():
            bg_task.cancel()
        proc = entry.get("proc")
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    return item


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: AdminUser = Depends(current_admin),
):
    """Lightweight chat about an existing app.

    Calls the Anthropic Messages API directly — no build pipeline, no git
    commits, no file edits. The Enhance panel's Chat mode uses this so admins
    can ask questions, brainstorm changes, or just discuss the app without
    triggering an expensive build run that might fail on a greeting like "hi".

    Uses Haiku for latency + cost. Retrieves the existing app's file list so
    Claude can give grounded answers about what's in the app.
    """
    import os
    import httpx
    from uuid import UUID as _UUID

    try:
        source_id = _UUID(body.source_task_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid source_task_id")

    async with session() as s:
        source = await _get_owned_task(s, source_id, user.email)
    if not source.built_app_slug:
        raise HTTPException(status_code=400, detail="Source task has no built app to chat about")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Chat unavailable — ANTHROPIC_API_KEY not configured")

    slug = source.built_app_slug
    app_dir = os.path.join(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps", slug)
    # Gather a compact file listing for context (file names only, no content)
    file_listing = ""
    try:
        entries = []
        for root, dirs, files in os.walk(app_dir):
            # Skip heavy/generated dirs
            dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__", ".pytest_cache", "data", ".git")]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), app_dir)
                entries.append(rel)
                if len(entries) >= 60:
                    break
            if len(entries) >= 60:
                break
        file_listing = "\n".join(f"  - {e}" for e in sorted(entries))
    except Exception:
        file_listing = "(file list unavailable)"

    system_prompt = (
        f"You are a helpful assistant for the AIUI decision engine, chatting with an admin "
        f"about the existing web app at apps/{slug}/. Answer their questions conversationally. "
        f"Keep replies concise (2-4 sentences for simple questions, up to ~8 sentences when "
        f"explaining or proposing a design). Use markdown sparingly — **bold** key phrases, "
        f"bullet lists only when listing multiple distinct items.\n\n"
        f"When the admin describes a concrete change they want made to the app, end your "
        f'reply with a one-line summary prefixed "BUILD_SUGGESTION:" that captures the '
        f"change in a form suitable for a build task (imperative, concrete). Example:\n"
        f"  BUILD_SUGGESTION: Add a search input that filters meetings by title (case-insensitive).\n"
        f"Only include BUILD_SUGGESTION when they're clearly ready to commit to a change — "
        f"not for hypothetical discussions. Never include it for greetings or pure questions.\n\n"
        f"APP FILES:\n{file_listing}"
    )

    messages = [m.model_dump() for m in body.history] + [
        {"role": "user", "content": body.message}
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 700,
                    "system": system_prompt,
                    "messages": messages,
                },
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Chat upstream error: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Claude API returned {r.status_code}: {r.text[:200]}")

    data = r.json()
    parts = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
    reply_text = "\n".join(p for p in parts if p).strip()
    if not reply_text:
        reply_text = "(no reply generated)"
    return ChatResponse(reply=reply_text)
