"""POST /outreach + GET /outreach/{task_id} + the _run_outreach coroutine."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

import outreach
from auth import current_user, CurrentUser
from claude_executor import parse_outcome
from db import session
from models import TaskItem, TaskExecution

logger = logging.getLogger("tasks.outreach")
router = APIRouter()


class OutreachRequest(BaseModel):
    role: str = ""
    location: str = ""
    jobdesc: str
    count: int = 10


class OutreachResponse(BaseModel):
    task_id: uuid.UUID


class OutreachStatusResponse(BaseModel):
    status: str
    found: int = 0
    sent: int = 0
    saved: int = 0
    sheet_url: str = ""
    text: str = ""


async def _process_outreach_result(raw_log: str, *, job_title: str, count: int) -> dict:
    """Pure: agent log -> summary dict."""
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0,
                "sheet_url": "", "text": (outcome.payload or "The search failed.").strip()[:500]}
    cand = outreach.extract_candidates(raw_log)
    found = len(cand.candidates)
    if found == 0:
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0, "sheet_url": "",
                "text": "I couldn't find engineers matching that — try a broader role or remove the location."}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    try:
        res = await outreach.post_outreach_to_n8n(job_title, batch)
    except Exception as exc:  # noqa: BLE001
        logger.error("outreach n8n POST failed: %s", exc)
        return {"status": "completed", "found": found, "sent": 0, "saved": len(batch),
                "sheet_url": "",
                "text": f"Found {found} engineer(s) but sending failed — they're saved; I'll retry sends."}
    sent = int(res.get("sent", 0)); saved = int(res.get("saved", len(batch)))
    sheet_url = res.get("sheet_url", "")
    return {"status": "completed", "found": found, "sent": sent, "saved": saved,
            "sheet_url": sheet_url,
            "text": outreach.format_outreach_summary(found, sent, saved, sheet_url)}


@router.post("/outreach", response_model=OutreachResponse, status_code=201)
async def start_outreach(body: OutreachRequest, user: CurrentUser = Depends(current_user)):
    import asyncio
    prompt = outreach.build_outreach_prompt(body.role, body.location, body.jobdesc, body.count)
    async with session() as s:
        item = TaskItem(
            meeting_id=uuid.uuid4(), action_type="OUTREACH",
            assignee_name=user.email.split("@")[0], assignee_email=user.email,
            description=f"Outreach: {body.role} {body.location}".strip(),
            priority="NICE_TO_HAVE", status="running", mode="ai", max_attempts=1)
        s.add(item); await s.flush()
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution); await s.commit()
        await s.refresh(item); await s.refresh(execution)
        task_id, exec_id = item.id, execution.id
    asyncio.create_task(_run_outreach(task_id, exec_id, prompt,
                                      job_title=body.role, count=body.count))
    return OutreachResponse(task_id=task_id)


@router.get("/outreach/{task_id}", response_model=OutreachStatusResponse)
async def get_outreach_status(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None or item.assignee_email != user.email:
        raise HTTPException(status_code=404, detail="not found")
    if item.status == "running":
        return OutreachStatusResponse(status="running")
    try:
        data = json.loads(item.result or "{}")
    except ValueError:
        data = {}
    return OutreachStatusResponse(
        status=data.get("status", "failed"), found=data.get("found", 0),
        sent=data.get("sent", 0), saved=data.get("saved", 0),
        sheet_url=data.get("sheet_url", ""), text=data.get("text", ""))


async def _run_outreach(task_id, execution_id, prompt, *, job_title: str, count: int):
    from routes_execution import _stream_claude  # LOCAL import (keep here, not module-top)
    try:
        raw_log = await _stream_claude(prompt, execution_id, task_id)
        summary = await _process_outreach_result(raw_log, job_title=job_title, count=count)
        final_status = "completed" if summary["status"] == "completed" else "failed"
        async with session() as s:
            await s.execute(update(TaskExecution).where(TaskExecution.id == execution_id)
                            .values(status="succeeded" if final_status == "completed" else "failed"))
            await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                            .values(status=final_status, result=json.dumps(summary)))
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("outreach run failed: %s", exc)
        async with session() as s:
            await s.execute(update(TaskItem).where(TaskItem.id == task_id).values(
                status="failed",
                result=json.dumps({"status": "failed", "text": f"Run error: {exc}"[:300]})))
            await s.commit()
