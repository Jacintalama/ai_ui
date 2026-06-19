"""POST /outreach + GET /outreach/{task_id} + the _run_outreach coroutine."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from typing import Literal

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
    mode: str = "auto"   # "auto" = find+send (Slack/legacy); "manual" = find+store
    direction: Literal["hire", "reverse"] = "hire"  # "hire" = find engineers; "reverse" = find companies
    reply_to: str = ""   # Reply-To header email: seeker's address (reverse) or recruiter's (hire)


class OutreachResponse(BaseModel):
    task_id: uuid.UUID


class OutreachStatusResponse(BaseModel):
    status: str
    found: int = 0
    sent: int = 0
    saved: int = 0
    sheet_url: str = ""
    text: str = ""
    candidates: list[dict] = []
    job_title: str = ""
    direction: str = "hire"
    role: str = ""
    location: str = ""


async def _process_outreach_result(raw_log: str, *, job_title: str, count: int,
                                   direction: str = "hire", location: str = "",
                                   reply_to: str = "") -> dict:
    """Pure: agent log -> summary dict."""
    meta = {"direction": direction, "role": job_title, "location": location,
            "reply_to": reply_to}
    noun = "compan(y/ies)" if direction == "reverse" else "engineer(s)"
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0,
                "sheet_url": "", "text": (outcome.payload or "The search failed.").strip()[:500],
                **meta}
    cand = outreach.extract_candidates(raw_log)
    found = len(cand.candidates)
    if found == 0:
        nf = ("I couldn't find companies hiring for that — try a broader role or drop the location."
              if direction == "reverse"
              else "I couldn't find engineers matching that — try a broader role or remove the location.")
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0, "sheet_url": "",
                "text": nf, **meta}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    try:
        res = await outreach.post_outreach_to_n8n(job_title, batch, reply_to=reply_to)
    except Exception as exc:  # noqa: BLE001
        logger.error("outreach n8n POST failed: %s", exc)
        return {"status": "completed", "found": found, "sent": 0, "saved": len(batch),
                "sheet_url": "",
                "text": f"Found {found} {noun} but sending failed — they're saved; I'll retry sends.",
                **meta}
    sent = int(res.get("sent", 0)); saved = int(res.get("saved", len(batch)))
    sheet_url = res.get("sheet_url", "")
    return {"status": "completed", "found": found, "sent": sent, "saved": saved,
            "sheet_url": sheet_url,
            "text": outreach.format_outreach_summary(found, sent, saved, sheet_url,
                                                     direction=direction),
            **meta}


def _process_outreach_find(raw_log: str, *, job_title: str, count: int,
                           direction: str = "hire", location: str = "",
                           reply_to: str = "") -> dict:
    """Manual mode: parse candidates, DON'T send. Store a review state."""
    meta = {"direction": direction, "role": job_title, "location": location,
            "reply_to": reply_to}
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "job_title": job_title,
                "text": (outcome.payload or "The search failed.").strip()[:500],
                **meta}
    cand = outreach.extract_candidates(raw_log)
    if not cand.candidates:
        nf = ("I couldn't find companies hiring for that — try a broader role."
              if direction == "reverse"
              else "I couldn't find engineers matching that — try a broader role.")
        return {"status": "failed", "found": 0, "job_title": job_title,
                "text": nf, **meta}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    return {"status": "review", "phase": "review", "job_title": job_title,
            "found": len(batch),
            "candidates": outreach.build_review_candidates(batch), **meta}


async def _load_review(task_id, user) -> tuple[object, dict]:
    """Return (item, data dict) for an OUTREACH task owned by user, else 404."""
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None or item.assignee_email != user.email:
        raise HTTPException(status_code=404, detail="not found")
    try:
        data = json.loads(item.result or "{}")
    except ValueError:
        data = {}
    return item, data


async def _save_candidates(task_id, data: dict, candidates: list[dict]) -> None:
    data = {**data, "candidates": candidates}
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                        .values(result=json.dumps(data)))
        await s.commit()


@router.post("/outreach", response_model=OutreachResponse, status_code=201)
async def start_outreach(body: OutreachRequest, user: CurrentUser = Depends(current_user)):
    import asyncio
    prompt = outreach.build_outreach_prompt(body.role, body.location, body.jobdesc, body.count,
                                            direction=body.direction)
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
                                      job_title=body.role, count=body.count,
                                      mode=body.mode, direction=body.direction,
                                      location=body.location, reply_to=body.reply_to))
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
        sheet_url=data.get("sheet_url", ""), text=data.get("text", ""),
        candidates=data.get("candidates", []), job_title=data.get("job_title", ""),
        direction=data.get("direction", "hire"), role=data.get("role", ""),
        location=data.get("location", ""))


@router.get("/outreach/{task_id}/candidates", response_model=OutreachStatusResponse)
async def get_outreach_candidates(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    if item.status == "running":
        return OutreachStatusResponse(status="running")
    return OutreachStatusResponse(
        status=data.get("status", "failed"), found=data.get("found", 0),
        text=data.get("text", ""), candidates=data.get("candidates", []),
        job_title=data.get("job_title", ""), direction=data.get("direction", "hire"),
        role=data.get("role", ""), location=data.get("location", ""))


class CandidatePatch(BaseModel):
    email: str | None = None
    subject: str | None = None
    body: str | None = None
    selected: bool | None = None
    selected_ids: list[str] | None = None   # set the whole selection at once


@router.patch("/outreach/{task_id}/candidates/{cid}", response_model=OutreachStatusResponse)
async def patch_outreach_candidate(task_id: uuid.UUID, cid: str, body: CandidatePatch,
                                   user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    candidates = data.get("candidates", [])
    if body.selected_ids is not None:
        candidates = outreach.set_selection(candidates, body.selected_ids)
    else:
        candidates = outreach.apply_candidate_edit(
            candidates, cid, email=body.email, subject=body.subject,
            body=body.body, selected=body.selected)
    await _save_candidates(task_id, data, candidates)
    return OutreachStatusResponse(status="review", candidates=candidates,
                                  found=len(candidates), job_title=data.get("job_title", ""),
                                  direction=data.get("direction", "hire"),
                                  role=data.get("role", ""), location=data.get("location", ""))


@router.post("/outreach/{task_id}/send", response_model=OutreachStatusResponse)
async def send_outreach(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    item, data = await _load_review(task_id, user)
    direction = data.get("direction", "hire")
    reply_to = data.get("reply_to", "")
    candidates = data.get("candidates", [])
    batch = outreach.sendable_candidates(candidates)
    if not batch:
        noun = "company" if direction == "reverse" else "engineer"
        return OutreachStatusResponse(status="review", candidates=candidates,
                                      text=f"Pick at least one {noun} with an email first.",
                                      job_title=data.get("job_title", ""),
                                      direction=direction, role=data.get("role", ""),
                                      location=data.get("location", ""))
    try:
        res = await outreach.post_outreach_to_n8n(data.get("job_title", ""), batch,
                                                  reply_to=reply_to)
    except Exception as exc:  # noqa: BLE001
        logger.error("manual outreach send failed: %s", exc)
        return OutreachStatusResponse(status="review", candidates=candidates,
                                      text="Sending failed — try again.",
                                      job_title=data.get("job_title", ""),
                                      direction=direction, role=data.get("role", ""),
                                      location=data.get("location", ""))
    sent_emails = {c.email.strip().lower() for c in batch}
    for c in candidates:
        if (c.get("email") or "").strip().lower() in sent_emails:
            c["status"] = "sent"
            c["selected"] = False
    new_data = {**data, "phase": "sent", "candidates": candidates,
                "status": "completed",
                "sent": int(res.get("sent", len(batch))),
                "saved": int(res.get("saved", len(batch))),
                "sheet_url": res.get("sheet_url", ""),
                "text": outreach.format_outreach_summary(
                    data.get("found", len(candidates)),
                    int(res.get("sent", len(batch))),
                    int(res.get("saved", len(batch))), res.get("sheet_url", ""),
                    direction=direction)}
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                        .values(result=json.dumps(new_data)))
        await s.commit()
    return OutreachStatusResponse(
        status="sent", candidates=candidates, sent=new_data["sent"],
        saved=new_data["saved"], sheet_url=new_data["sheet_url"], text=new_data["text"],
        job_title=data.get("job_title", ""), direction=direction,
        role=data.get("role", ""), location=data.get("location", ""))


async def _run_outreach(task_id, execution_id, prompt, *, job_title: str,
                        count: int, mode: str = "auto", direction: str = "hire",
                        location: str = "", reply_to: str = ""):
    from routes_execution import _stream_claude  # LOCAL import (keep here, not module-top)
    try:
        raw_log = await _stream_claude(prompt, execution_id, task_id)
        if mode == "manual":
            summary = _process_outreach_find(raw_log, job_title=job_title, count=count,
                                             direction=direction, location=location,
                                             reply_to=reply_to)
        else:
            summary = await _process_outreach_result(raw_log, job_title=job_title, count=count,
                                                     direction=direction, location=location,
                                                     reply_to=reply_to)
        final_status = "completed" if summary["status"] in ("completed", "review") else "failed"
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
