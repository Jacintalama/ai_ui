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
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

from db import session
from models import Schedule

router = APIRouter(prefix="/schedules")

# Each schedule spawns a Claude Code agent run and concurrency is capped at 3
# (scheduler.py) to avoid OOM on a 3.8GB box, so an unbounded number of
# frequent schedules is a self-DoS. Mirrors what webhook-handler's own cron
# already enforces (max_user_jobs / min_interval_minutes).
MAX_SCHEDULES_PER_USER = 10
MIN_INTERVAL_MINUTES = 15


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
    run_once: bool = False
    delivery_channel_id: str | None = None
    delivery_platform: str = "discord"
    kind: str = "agent"
    video_config: dict | None = None


def _validate_kind(kind: str, video_config: dict | None) -> None:
    """400 on an unknown kind or a video schedule without a usable URL."""
    if kind not in ("agent", "video"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'video'")
    if kind == "video":
        url = ((video_config or {}).get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=400,
                                detail="video_config.url must be an http(s) URL")


# A fixed base makes the calculation deterministic — otherwise the same cron
# expression could pass or fail depending on when the request arrives.
_INTERVAL_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def min_interval_minutes(cron_expr: str) -> float:
    """Smallest gap between consecutive fire times, in minutes.

    Four fire times give three gaps, which is enough to catch a step
    (`*/5`) or a comma list (`0,30`) rather than only the literal
    `* * * * *`. Never raises: a malformed expression is rejected upstream by
    croniter.is_valid, and this must not be what 500s a request.
    """
    try:
        from croniter import croniter
        it = croniter(cron_expr, _INTERVAL_BASE)
        times = [it.get_next(datetime) for _ in range(4)]
    except Exception:  # noqa: BLE001 - unparseable is handled by the caller
        return 0.0
    gaps = [(times[i + 1] - times[i]).total_seconds() / 60
            for i in range(len(times) - 1)]
    return min(gaps) if gaps else 0.0


@router.get("")
async def list_schedules(
    platform: str = Query(default=""),
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> list[dict[str, Any]]:
    is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    async with session() as s:
        stmt = select(Schedule)
        if not is_operator:
            stmt = stmt.where(Schedule.user_email == scoped_email)
        if platform:
            stmt = stmt.where(Schedule.delivery_platform == platform)
        rows = (await s.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
async def create_schedule(
    body: CreateScheduleIn,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
    x_user_admin: str = Header(default=""),
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

    _validate_kind(body.kind, body.video_config)

    # Operators (X-Cron-Secret) and admins keep the old unbounded behaviour:
    # the cap exists to stop casual self-DoS, not as a security boundary.
    is_admin = x_user_admin.strip().lower() == "true"
    if not is_operator and not is_admin:
        gap = min_interval_minutes(body.cron_expr)
        if gap and gap < MIN_INTERVAL_MINUTES:
            raise HTTPException(
                status_code=400,
                detail=(f"The shortest repeat is every {MIN_INTERVAL_MINUTES} "
                        f"minutes. That schedule would run every "
                        f"{int(gap)} minute(s)."),
            )
        # Counting by fetching rows rather than func.count(): the ceiling is 10
        # rows, and it reuses the mock shape the existing route tests prove.
        async with session() as s:
            mine = (await s.execute(
                select(Schedule).where(Schedule.user_email == owner)
            )).scalars().all()
        if len(mine) >= MAX_SCHEDULES_PER_USER:
            raise HTTPException(
                status_code=429,
                detail=(f"You already have {MAX_SCHEDULES_PER_USER} scheduled "
                        f"tasks. Delete one first."),
            )

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
            run_once=body.run_once,
            delivery_channel_id=body.delivery_channel_id,
            delivery_platform=body.delivery_platform,
            kind=body.kind,
            video_config=body.video_config,
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
        "delivery_platform": sch.delivery_platform,
        "kind": sch.kind,
    }
