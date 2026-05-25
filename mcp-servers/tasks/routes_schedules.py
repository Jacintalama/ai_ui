"""CRUD for tasks.schedules — dual-auth (operator OR end-user).

Two ways to authenticate:
1. **Operator path:** `X-Cron-Secret: <CRON_SHARED_SECRET>` — used by
   scripts/manage_schedules.py and any cron-runner. Operator can act on
   any user's schedules and must specify `user_email` in the body.
2. **End-user path:** `X-User-Email: <email>` — injected by the API gateway
   after JWT validation. The schedule is scoped to that email; the body's
   `user_email` is ignored and replaced. Reads/deletes/updates only see
   schedules owned by the caller.

Without EITHER header, every call returns 403.
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


def _resolve_caller(
    x_cron_secret: str, x_user_email: str,
) -> tuple[bool, str | None]:
    """Decide who the caller is.

    Returns (is_operator, scoped_email). Raises 403 if neither auth path
    succeeds. The end-user path requires a non-empty X-User-Email header;
    the operator path requires the matching shared secret.
    """
    expected = _cron_secret()
    if expected and x_cron_secret == expected:
        return True, None  # operator can target any user
    if x_user_email:
        return False, x_user_email  # gateway already JWT-validated this
    raise HTTPException(
        status_code=403,
        detail="Missing auth: provide X-Cron-Secret OR X-User-Email",
    )


class CreateScheduleIn(BaseModel):
    user_email: str | None = None  # ignored for end-user calls
    name: str
    cron_expr: str
    tz: str = "Asia/Manila"
    persona: str = ""
    prompt: str = Field(min_length=1)
    enabled: bool = True
    delivery_channel_id: str | None = None


@router.get("")
async def list_schedules(
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> list[dict[str, Any]]:
    is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    async with session() as s:
        stmt = select(Schedule)
        if not is_operator:
            stmt = stmt.where(Schedule.user_email == scoped_email)
        rows = (await s.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
async def create_schedule(
    body: CreateScheduleIn,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, Any]:
    is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    # For end-user calls, force the schedule onto the JWT-authenticated email.
    # For operator calls, the body must specify user_email.
    if is_operator:
        if not body.user_email:
            raise HTTPException(
                status_code=400,
                detail="user_email required when using X-Cron-Secret",
            )
        owner = body.user_email
    else:
        owner = scoped_email

    # Validate cron expression — reject malformed input before persisting
    # so we never write a schedule the ticker can't parse.
    from croniter import croniter
    if not croniter.is_valid(body.cron_expr):
        raise HTTPException(status_code=400, detail="invalid cron_expr")

    sid = uuid.uuid4()
    async with session() as s:
        s.add(Schedule(
            id=sid,
            user_email=owner,
            name=body.name,
            cron_expr=body.cron_expr,
            tz=body.tz,
            persona=body.persona,
            prompt=body.prompt,
            enabled=body.enabled,
            delivery_channel_id=body.delivery_channel_id,
        ))
        await s.commit()
    return {"id": str(sid)}


async def _scoped_schedule(
    schedule_id: str, scoped_email: str | None,
) -> Schedule:
    """Fetch a schedule by id, with ownership check for end-user calls.
    404 if missing, 403 if owned by someone else."""
    async with session() as s:
        sched = (await s.execute(
            select(Schedule).where(Schedule.id == uuid.UUID(schedule_id))
        )).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="not found")
    if scoped_email is not None and sched.user_email != scoped_email:
        # End-user trying to touch someone else's schedule — same 404 as
        # missing so we don't leak existence.
        raise HTTPException(status_code=404, detail="not found")
    return sched


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, str]:
    _, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    await _scoped_schedule(schedule_id, scoped_email)  # raises if not owner
    async with session() as s:
        await s.execute(delete(Schedule).where(Schedule.id == uuid.UUID(schedule_id)))
        await s.commit()
    return {"status": "deleted"}


@router.post("/{schedule_id}/enable")
async def enable_schedule(
    schedule_id: str,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, str]:
    _, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    await _scoped_schedule(schedule_id, scoped_email)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(enabled=True)
        )
        await s.commit()
    return {"status": "enabled"}


@router.post("/{schedule_id}/disable")
async def disable_schedule(
    schedule_id: str,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, str]:
    _, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    await _scoped_schedule(schedule_id, scoped_email)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(enabled=False)
        )
        await s.commit()
    return {"status": "disabled"}


@router.post("/{schedule_id}/run-now")
async def run_now(
    schedule_id: str,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, str]:
    """Bypass cron and fire this schedule immediately. Useful for smoke
    tests and for kicking off a one-off run from the CLI or chat."""
    _, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    sched = await _scoped_schedule(schedule_id, scoped_email)
    import asyncio
    from scheduler import _finalize_run
    asyncio.create_task(_finalize_run(sched))
    return {"status": "dispatched"}


class UpdateScheduleIn(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    prompt: str | None = None


@router.patch("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    body: UpdateScheduleIn,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, str]:
    _, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    await _scoped_schedule(schedule_id, scoped_email)  # 404 if missing / not owner
    values: dict[str, Any] = {}
    if body.name is not None:
        values["name"] = body.name
    if body.cron_expr is not None:
        from croniter import croniter
        if not croniter.is_valid(body.cron_expr):
            raise HTTPException(status_code=400, detail="invalid cron_expr")
        values["cron_expr"] = body.cron_expr
    if body.prompt is not None:
        values["prompt"] = body.prompt
    if values:
        async with session() as s:
            await s.execute(
                update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(**values)
            )
            await s.commit()
    return {"status": "updated"}


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
        "delivery_channel_id": sch.delivery_channel_id,
    }
