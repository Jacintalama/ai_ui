"""CRUD for tasks.schedules — protected by the X-Cron-Secret header.

This is the operator-facing API behind scripts/manage_schedules.py. It is
NOT mounted under /api or behind admin JWT auth because the smoke-test
cadence (and future cron-runner-from-N8N) hits it without a user session.
Auth is a shared secret in the X-Cron-Secret header; the value comes from
CRON_SHARED_SECRET on the tasks service env.

Without the secret set in the environment, every call returns 403.
"""
import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

from db import session
from models import Schedule

router = APIRouter(prefix="/schedules")


def _cron_secret() -> str:
    """Read the secret from env at call time so tests can monkeypatch it."""
    return os.environ.get("CRON_SHARED_SECRET", "")


def _require_secret(x_cron_secret: str) -> None:
    """403 if the header is missing OR doesn't match. Empty env value also
    fails-closed: a misconfigured deploy must not silently accept any input."""
    expected = _cron_secret()
    if not expected or x_cron_secret != expected:
        raise HTTPException(status_code=403, detail="Bad or missing X-Cron-Secret")


class CreateScheduleIn(BaseModel):
    user_email: str
    name: str
    cron_expr: str
    tz: str = "Asia/Manila"
    persona: str = ""
    prompt: str = Field(min_length=1)
    enabled: bool = True


@router.get("")
async def list_schedules(x_cron_secret: str = Header(default="")) -> list[dict[str, Any]]:
    _require_secret(x_cron_secret)
    async with session() as s:
        rows = (await s.execute(select(Schedule))).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
async def create_schedule(
    body: CreateScheduleIn,
    x_cron_secret: str = Header(default=""),
) -> dict[str, Any]:
    _require_secret(x_cron_secret)
    # Validate cron expression — reject malformed input before persisting
    # so we never write a schedule the ticker can't parse.
    from croniter import croniter
    if not croniter.is_valid(body.cron_expr):
        raise HTTPException(status_code=400, detail="invalid cron_expr")

    sid = uuid.uuid4()
    async with session() as s:
        s.add(Schedule(
            id=sid,
            user_email=body.user_email,
            name=body.name,
            cron_expr=body.cron_expr,
            tz=body.tz,
            persona=body.persona,
            prompt=body.prompt,
            enabled=body.enabled,
        ))
        await s.commit()
    return {"id": str(sid)}


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str, x_cron_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_secret(x_cron_secret)
    async with session() as s:
        await s.execute(delete(Schedule).where(Schedule.id == uuid.UUID(schedule_id)))
        await s.commit()
    return {"status": "deleted"}


@router.post("/{schedule_id}/enable")
async def enable_schedule(
    schedule_id: str, x_cron_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_secret(x_cron_secret)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(enabled=True)
        )
        await s.commit()
    return {"status": "enabled"}


@router.post("/{schedule_id}/disable")
async def disable_schedule(
    schedule_id: str, x_cron_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_secret(x_cron_secret)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(enabled=False)
        )
        await s.commit()
    return {"status": "disabled"}


@router.post("/{schedule_id}/run-now")
async def run_now(
    schedule_id: str, x_cron_secret: str = Header(default=""),
) -> dict[str, str]:
    """Bypass cron and fire this schedule immediately. Useful for smoke
    tests and for kicking off a one-off run from the CLI."""
    _require_secret(x_cron_secret)
    async with session() as s:
        sched = (await s.execute(
            select(Schedule).where(Schedule.id == uuid.UUID(schedule_id))
        )).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="not found")
    import asyncio
    from scheduler import _finalize_run
    asyncio.create_task(_finalize_run(sched))
    return {"status": "dispatched"}


def _serialize(sch: Schedule) -> dict[str, Any]:
    return {
        "id": str(sch.id),
        "user_email": sch.user_email,
        "name": sch.name,
        "cron_expr": sch.cron_expr,
        "tz": sch.tz,
        "persona": sch.persona,
        "prompt": sch.prompt,
        "enabled": sch.enabled,
        "last_run_at": sch.last_run_at.isoformat() if sch.last_run_at else None,
        "last_run_status": sch.last_run_status,
    }
