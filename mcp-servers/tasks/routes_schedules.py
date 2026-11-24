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
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

from db import session
from models import Schedule

logger = logging.getLogger(__name__)

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
    # Which AI Agent runs this, or None for the executor schedules have always
    # used. Not validated against the model table here: the agent has to be
    # visible to the OWNER at run time, and that is a different question from
    # whether it exists right now.
    agent_id: str | None = None
    tool_mode: str | None = None
    video_config: dict | None = None


async def _agents_for_owner(email: str):
    """This person's agents. A seam, so tests need no Open WebUI.

    Imported inside the function because routes_agent_turn pulls in the whole
    turn path, and this router is mounted twice (bare and under /api/tasks).
    """
    from routes_agent_turn import _agents_for
    return await _agents_for(email)


async def _default_agent(owner: str) -> dict | None:
    """The agent a schedule runs as when the client could not name one.

    Exists because webhook-handler's create_schedule has no agent_id
    parameter, so a schedule made from Discord or Slack could otherwise only
    be one that fails every time it fires.

    The oldest, then the lowest id. The id is not a tie-break for show:
    a user's starter agents are seeded in the SAME SECOND, so on real data
    the oldest is always a tie. Measured on production 2026-09-24, all three
    accounts, e.g. agent-inbox-triage-0002 (Mia) and
    agent-research-assistant-0001 (Ada) both at 1787554470. Without the id
    the winner is whatever order the listing happened to return, and the
    first live call after deploy picked the receptionist for an account whose
    Ada is the project manager.

    Which agent it lands on is arbitrary. That is acceptable only because the
    choice is RECORDED on the row and named back to the caller, so it shows on
    the card, gets said in the bot's confirmation, and can be changed. It must
    at least be the same arbitrary answer every time.
    """
    try:
        agents = await _agents_for_owner(owner)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not list agents to pick a default for %s",
                       owner, exc_info=True)
        return None
    rows = [a for a in (agents or [])
            if isinstance(a, dict) and a.get("id")]
    if not rows:
        return None
    # created_at is seconds on an Open WebUI model row. Missing sorts first
    # rather than raising, which keeps the pick deterministic either way.
    return sorted(rows, key=lambda a: (a.get("created_at") or 0,
                                       str(a.get("id") or "")))[0]


#: Said when nobody can be picked. _agents_for returns [] on any doubt,
#: including a listing that was cut short, so this cannot tell "you have none"
#: from "we could not check" and must not claim either.
NO_AGENT_TO_PICK = ("This schedule needs an agent to run it, and none could "
                    "be chosen for you. Pick one on the Schedules page, or "
                    "create an agent on the Agents page first.")


def _validate_kind(kind: str, video_config: dict | None) -> None:
    """400 on an unknown kind or a video schedule without a usable URL."""
    if kind not in ("agent", "video"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'video'")
    if kind == "video":
        url = ((video_config or {}).get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=400,
                                detail="video_config.url must be an http(s) URL")


#: The only stored values agent_runner treats as full access is exactly
#: "full"; everything else, including None, is read_only. That fail-closed
#: mapping is only meaningful if the column cannot hold anything OTHER than
#: these two values in the first place -- otherwise a typo like "ask" would
#: store happily and just happen to read as read_only today, with nothing
#: stopping the read side from drifting later and turning it into full
#: access by accident.
_VALID_TOOL_MODES = frozenset({"read_only", "full"})


def _validate_tool_mode(tool_mode: str | None) -> None:
    """400 on anything other than 'read_only', 'full', or absent."""
    if tool_mode is not None and tool_mode not in _VALID_TOOL_MODES:
        raise HTTPException(
            status_code=400,
            detail="tool_mode must be 'read_only' or 'full'",
        )


# A fixed base makes the calculation deterministic — otherwise the same cron
# expression could pass or fail depending on when the request arrives.
#
# Late in the day, not midnight: from 00:00 all four samples land inside the
# same day, so the window closes before the 23:59 -> 00:00 wrap and
# `0,30,59 0,23 * * *` reads as 29 minutes when it really fires one minute
# apart. Starting at 23:45 puts that wrap in the very first gap. It does not
# close the equivalent day-of-week wrap (`0,59 0,23 * * 0,1`, still read as
# 59) — 2026-01-01 is a Thursday, and moving the base onto a Sunday just trades
# that miss for Sunday-only expressions. That one needs a different algorithm.
_INTERVAL_BASE = datetime(2026, 1, 1, 23, 45, tzinfo=timezone.utc)


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


def _is_admin(x_user_admin: str) -> bool:
    """The gateway strips X-User-Admin from the client request and re-sets it
    after validating the JWT (api-gateway/main.py), so the route can trust it."""
    return x_user_admin.strip().lower() == "true"


def _holds_a_slot(sched: Schedule) -> bool:
    """Does this row still cost the box anything?

    A one-off that has fired does not: scheduler.fire_values sets
    enabled=False on it and nothing ever deletes the row, so ten of them would
    pin a user at the ceiling forever — told they "already have 10 scheduled
    tasks" about schedules that can never run again. A one-off that has NOT
    fired yet is still a queued agent run and does hold its slot.
    """
    return not (getattr(sched, "run_once", False)
                and not getattr(sched, "enabled", True))


async def _enforce_count_cap(owner: str) -> None:
    """429 when `owner` already holds every slot they are allowed.

    Shared by create and by enable — a spent one-off does not count, so
    re-enabling one takes a slot back and has to ask the same question.

    Counting by fetching rows rather than func.count(): the ceiling is 10 rows,
    it reuses the mock shape the existing route tests prove, and it lets
    _holds_a_slot stay a plain predicate a test can drive instead of SQL no
    mock can evaluate.
    """
    async with session() as s:
        mine = (await s.execute(
            select(Schedule).where(Schedule.user_email == owner)
        )).scalars().all()
    if len([r for r in mine if _holds_a_slot(r)]) >= MAX_SCHEDULES_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=(f"You already have {MAX_SCHEDULES_PER_USER} scheduled "
                    f"tasks. Delete one first."),
        )


def _enforce_interval_floor(
    cron_expr: str, *, is_operator: bool, is_admin: bool,
) -> None:
    """400 when a regular user asks for a repeat faster than the floor.

    Shared by create AND update. Checking only croniter.is_valid on the update
    path let a user create `0 9 * * *`, then PATCH it to `* * * * *` from
    either bot's Edit modal — which made the whole cap decorative. Keeping one
    helper is what stops the two paths drifting apart again.

    Operators (X-Cron-Secret) and admins keep the old unbounded behaviour: the
    cap exists to stop casual self-DoS, not as a security boundary.
    """
    if is_operator or is_admin:
        return
    gap = min_interval_minutes(cron_expr)
    # gap <= 0 means "could not be measured", not "fires instantly": an
    # expression like `0 0 30 2 *` is valid to croniter but raises inside
    # get_next, so it lands here as 0.0. It can never fire, so let it through —
    # explicitly, rather than by falling through a falsy zero.
    if gap <= 0 or gap >= MIN_INTERVAL_MINUTES:
        return
    raise HTTPException(
        status_code=400,
        detail=(f"The shortest repeat is every {MIN_INTERVAL_MINUTES} "
                f"minutes. That schedule would run every "
                f"{int(gap)} minute(s)."),
    )


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
    out = [_serialize(r) for r in rows]
    if is_operator:
        # The operator poll gets exactly what it got before. Nothing on that
        # side draws run marks, and in operator mode this list is EVERY
        # user's schedules, so attaching a week to each would be the
        # platform's whole run history on a route that fires on a timer.
        return out
    # The week travels with the list: see `runs_for_schedules`. Deferred
    # import for the same reason `run_now` defers its one below, that
    # scheduler pulls in the agent runner and this module is imported while
    # the app is still being built.
    from scheduler import runs_for_schedules, with_runs
    return with_runs(out, await runs_for_schedules([r["id"] for r in out]))


#: How many outputs the Cron Outputs page shows, and the most it may ask for.
OUTPUTS_DEFAULT = 20
OUTPUTS_MAX = 50

#: Newest runs first across all of ONE person's schedules, joined for the
#: name. Scoped on `tasks.schedules.user_email`, the owner column every other
#: route here trusts, not on the copy the run row carries. `{unread}` is
#: either empty or the unread-only filter, both fixed strings.
_OUTPUTS_SQL = (
    "SELECT r.id, r.schedule_id, s.name, r.started_at, r.finished_at, "
    "       r.status, r.result, r.unread "
    "FROM tasks.schedule_run r "
    "JOIN tasks.schedules s ON s.id = r.schedule_id "
    "WHERE s.user_email = :email{unread} "
    "ORDER BY r.started_at DESC "
    "LIMIT :n")
_UNREAD_ONLY = " AND r.unread"

#: How many of this person's outputs are unread: the red count on Cron Jobs.
_UNREAD_COUNT_SQL = (
    "SELECT count(*) FROM tasks.schedule_run r "
    "JOIN tasks.schedules s ON s.id = r.schedule_id "
    "WHERE s.user_email = :email AND r.unread")

#: Mark ONE run read or unread, only if it belongs to this person.
_MARK_ONE_SQL = (
    "UPDATE tasks.schedule_run SET unread = :unread "
    "WHERE id = CAST(:id AS UUID) "
    "AND schedule_id IN (SELECT id FROM tasks.schedules "
    "                    WHERE user_email = :email) "
    "RETURNING id")

#: Mark everything this person has read, or everything from one cron.
_MARK_ALL_SQL = (
    "UPDATE tasks.schedule_run SET unread = false "
    "WHERE unread "
    "AND schedule_id IN (SELECT id FROM tasks.schedules "
    "                    WHERE user_email = :email{one})")
_ONE_SCHEDULE = " AND id = CAST(:schedule_id AS UUID)"


def outputs_sql(unread_only: bool) -> str:
    """The listing statement, with or without the unread filter. Pure."""
    return _OUTPUTS_SQL.format(unread=_UNREAD_ONLY if unread_only else "")


def mark_all_sql(one_schedule: bool) -> str:
    """The mark-all statement, for everything or for one cron. Pure."""
    return _MARK_ALL_SQL.format(one=_ONE_SCHEDULE if one_schedule else "")


def valid_uuid(value: str | None) -> str | None:
    """The id as a canonical UUID string, or None. Pure. Checked before the
    database sees it, so a bad id is a 404 and never a 500 from a failed
    cast."""
    try:
        return str(uuid.UUID(str(value or "").strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def outputs_limit(limit: int | None) -> int:
    """The number of outputs to read, never fewer than 1 nor more than the
    cap. Pure. A page asking for 10,000 runs of 8,000 characters each is
    80MB of text on one request, on a 3.8GB box."""
    try:
        n = int(limit) if limit is not None else OUTPUTS_DEFAULT
    except (TypeError, ValueError):
        n = OUTPUTS_DEFAULT
    return max(1, min(OUTPUTS_MAX, n))


def shape_output(row) -> dict[str, Any]:
    """One run as the Cron Outputs page reads it. Pure.

    Unlike a run MARK, which carries text only for a run that went wrong,
    this carries the whole stored answer: reading the answer is the page's
    entire job. A run with no finish is reported as failed, for the reason
    `scheduler.run_row` gives: a process that died mid run never writes one.
    """
    def _get(key):
        return row.get(key) if isinstance(row, dict) else getattr(row, key, None)

    started, finished = _get("started_at"), _get("finished_at")
    status = str(_get("status") or "")
    if not finished or status == "running":
        status = "failed"
    return {
        "schedule_id": str(_get("schedule_id") or ""),
        "name": str(_get("name") or "Untitled"),
        "at": started.isoformat() if hasattr(started, "isoformat") else started,
        "finished_at": (finished.isoformat()
                        if hasattr(finished, "isoformat") else finished),
        "status": status,
        "ok": status == "completed",
        "result": str(_get("result") or ""),
        "id": str(_get("id") or ""),
        "unread": bool(_get("unread")),
    }


def _owner(x_cron_secret: str, x_user_email: str) -> str:
    """The one person an outputs call is about, or "" for nobody.

    The operator secret alone names nobody, so it gets nothing rather than
    every user's answers.
    """
    _is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    return scoped_email or x_user_email or ""


@router.get("/outputs")
async def list_outputs(
    limit: int = Query(default=OUTPUTS_DEFAULT),
    unread_only: bool = Query(default=False),
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> list[dict[str, Any]]:
    """What this person's cron jobs answered, newest first, with the text,
    and whether each one has been read."""
    email = _owner(x_cron_secret, x_user_email)
    if not email:
        return []
    from sqlalchemy import text
    async with session() as s:
        rows = await s.execute(text(outputs_sql(unread_only)),
                               {"email": email, "n": outputs_limit(limit)})
        return [shape_output(r) for r in rows.mappings().all()]


@router.get("/outputs/unread")
async def unread_outputs(
    limit: int = Query(default=3),
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, Any]:
    """The red count on Cron Jobs, and the newest unread answers for the
    sidebar notice. One request, asked every 30 seconds per open tab."""
    email = _owner(x_cron_secret, x_user_email)
    if not email:
        return {"count": 0, "items": []}
    from sqlalchemy import text
    n = max(0, min(10, int(limit or 0)))
    async with session() as s:
        count = (await s.execute(text(_UNREAD_COUNT_SQL),
                                 {"email": email})).scalar() or 0
        items = []
        if n and count:
            rows = await s.execute(text(outputs_sql(True)),
                                   {"email": email, "n": n})
            items = [shape_output(r) for r in rows.mappings().all()]
    return {"count": int(count), "items": items}


class MarkReadIn(BaseModel):
    read: bool = True


@router.post("/outputs/{run_id}/read")
async def mark_output_read(
    run_id: str,
    body: MarkReadIn | None = None,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, Any]:
    """Mark one output read (opening it) or unread again. Only the owner's:
    an id that is not theirs is a 404, exactly like one that does not exist."""
    email = _owner(x_cron_secret, x_user_email)
    rid = valid_uuid(run_id)
    if not email or not rid:
        raise HTTPException(status_code=404, detail="No such output")
    read = True if body is None else bool(body.read)
    from sqlalchemy import text
    async with session() as s:
        hit = (await s.execute(text(_MARK_ONE_SQL),
                               {"id": rid, "email": email,
                                "unread": not read})).first()
        if not hit:
            raise HTTPException(status_code=404, detail="No such output")
        await s.commit()
        count = (await s.execute(text(_UNREAD_COUNT_SQL),
                                 {"email": email})).scalar() or 0
    return {"ok": True, "id": rid, "unread": not read, "count": int(count)}


class MarkAllIn(BaseModel):
    schedule_id: str | None = None


@router.post("/outputs/read-all")
async def mark_all_outputs_read(
    body: MarkAllIn | None = None,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
) -> dict[str, Any]:
    """Mark every unread output read, or only one cron's."""
    email = _owner(x_cron_secret, x_user_email)
    if not email:
        raise HTTPException(status_code=403, detail="Nobody to mark for")
    sid = None
    if body is not None and body.schedule_id:
        sid = valid_uuid(body.schedule_id)
        if not sid:
            raise HTTPException(status_code=404, detail="No such cron job")
    params: dict[str, Any] = {"email": email}
    if sid:
        params["schedule_id"] = sid
    from sqlalchemy import text
    async with session() as s:
        await s.execute(text(mark_all_sql(bool(sid))), params)
        await s.commit()
        count = (await s.execute(text(_UNREAD_COUNT_SQL),
                                 {"email": email})).scalar() or 0
    return {"ok": True, "count": int(count)}


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
    _validate_tool_mode(body.tool_mode)

    is_admin = _is_admin(x_user_admin)
    _enforce_interval_floor(body.cron_expr, is_operator=is_operator,
                            is_admin=is_admin)
    if not is_operator and not is_admin:
        await _enforce_count_cap(owner)

    # Every schedule that runs an agent gets one now, named by the client or
    # chosen here. A video schedule renders a walkthrough and never reaches
    # the agent path, so requiring one there would block a feature that works.
    agent_id = (body.agent_id or "").strip()
    agent_name = ""
    if not agent_id and body.kind != "video":
        picked = await _default_agent(owner)
        if not picked:
            raise HTTPException(status_code=400, detail=NO_AGENT_TO_PICK)
        agent_id = str(picked.get("id") or "")
        agent_name = str(picked.get("name") or "")

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
            # Never None for an agent schedule: either the client named one
            # or _default_agent picked it above.
            agent_id=agent_id or None,
            # None means read_only, the safe default for an unattended run.
            tool_mode=body.tool_mode,
        ))
        await s.commit()
    # The agent comes back so a caller that could not name one can still say
    # who will run it. A bot that leaves the person to find out at 7pm is how
    # two of these ran for months doing the wrong thing unnoticed.
    return {"id": str(sid), "agent_id": agent_id or None,
            "agent_name": agent_name}


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
    x_user_admin: str = Header(default=""),
) -> dict[str, str]:
    is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    sched = await _scoped_schedule(schedule_id, scoped_email)
    # A spent one-off stopped counting (_holds_a_slot), so switching it back on
    # takes a slot back and has to pass the cap again. Otherwise "fire ten,
    # create ten more, resurrect the first ten" repeats without bound. A row
    # that still holds its slot — an ordinary paused schedule — is untouched:
    # it was never released, so resuming it adds nothing.
    if (not is_operator and not _is_admin(x_user_admin)
            and not _holds_a_slot(sched)):
        await _enforce_count_cap(sched.user_email)
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
    x_user_admin: str = Header(default=""),
) -> dict[str, str]:
    """Bypass cron and fire this schedule immediately. Useful for smoke
    tests and for kicking off a one-off run from the CLI or chat.

    Refused while a run for this schedule is already in flight. Each run spawns
    a Claude Code agent; scheduler._RUN_SEMAPHORE caps concurrency at 3 so the
    box will not OOM, but a semaphore is a queue rather than a bound — without
    this, a burst of clicks piles up behind it and the genuine cron-scheduled
    runs starve at the back. "It is already running" is both the honest answer
    and the bound, and needs no quota to tune.

    The signal is scheduler._IN_FLIGHT, marked by dispatch_run for the cron
    tick and this route alike, so a live cron run counts too. Not the
    `last_run_status` column: that outlives the asyncio.Task it would describe,
    so a crash would wedge run-now permanently (see scheduler._IN_FLIGHT).

    Operators and admins are exempt from the refusal — as with every other
    schedule limit — but never from the marking, or a run they started would
    look like an idle schedule to its owner.
    """
    is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    # Scoped first, so a stranger cannot learn from a 409 that someone else's
    # schedule exists and is busy.
    sched = await _scoped_schedule(schedule_id, scoped_email)
    from scheduler import dispatch_run, is_run_in_flight
    if (not is_operator and not _is_admin(x_user_admin)
            and is_run_in_flight(sched.id)):
        raise HTTPException(
            status_code=409,
            detail=("This scheduled task is already running. Wait for it to "
                    "finish, then run it again."),
        )
    dispatch_run(sched)
    return {"status": "dispatched"}


class UpdateScheduleIn(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    prompt: str | None = None
    # Whether this cron's new outputs count in the red number (migration
    # 073, cron_quiet). Muting also reads what is already unread from it.
    notify: bool | None = None
    # The Edit button on the Cron Jobs page (2026-11-24) sends these too.
    # Absent means unchanged, which is all the Discord edit modal sends.
    agent_id: str | None = None
    tool_mode: str | None = None


#: Said when an edit would leave a schedule with nobody to run it.
NO_AGENT_ON_EDIT = ("A schedule needs an agent to run it. Pick one of your "
                    "agents under Run as.")


@router.patch("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    body: UpdateScheduleIn,
    x_cron_secret: str = Header(default=""),
    x_user_email: str = Header(default=""),
    x_user_admin: str = Header(default=""),
) -> dict[str, str]:
    is_operator, scoped_email = _resolve_caller(x_cron_secret, x_user_email)
    sched = await _scoped_schedule(schedule_id, scoped_email)  # 404 if missing / not owner
    values: dict[str, Any] = {}
    if body.notify is not None:
        values["notify"] = bool(body.notify)
    # Every check runs before anything is written, so one refused field
    # stops the whole edit rather than saving the rest of it.
    _validate_tool_mode(body.tool_mode)
    if body.tool_mode is not None:
        values["tool_mode"] = body.tool_mode
    if body.agent_id is not None:
        # Create picks a default when none is named; an edit has one
        # already, so a blank here can only mean "remove it", which would
        # leave a schedule that fails every time it fires.
        agent_id = body.agent_id.strip()
        if not agent_id:
            raise HTTPException(status_code=400, detail=NO_AGENT_ON_EDIT)
        values["agent_id"] = agent_id
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="name cannot be blank")
        values["name"] = body.name
    if body.cron_expr is not None:
        from croniter import croniter
        if not croniter.is_valid(body.cron_expr):
            raise HTTPException(status_code=400, detail="invalid cron_expr")
        # The same floor as create — otherwise the Edit modal is a bypass.
        # The COUNT cap deliberately does not apply: editing a row adds none.
        _enforce_interval_floor(body.cron_expr, is_operator=is_operator,
                                is_admin=_is_admin(x_user_admin))
        values["cron_expr"] = body.cron_expr
    if body.prompt is not None:
        if not body.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt cannot be blank")
        values["prompt"] = body.prompt
    if values:
        async with session() as s:
            await s.execute(
                update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(**values)
            )
            if values.get("notify") is False:
                # Muting a cron takes what it already has unread off the red
                # number too, the way muting a chat does. Still in the inbox.
                from sqlalchemy import text
                await s.execute(text(mark_all_sql(True)),
                                {"email": sched.user_email,
                                 "schedule_id": str(sched.id)})
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
        "last_result": getattr(sch, "last_result", None),
        "last_result_at": (sch.last_result_at.isoformat()
                           if getattr(sch, "last_result_at", None) else None),
        "delivery_channel_id": sch.delivery_channel_id,
        "delivery_platform": sch.delivery_platform,
        "kind": sch.kind,
        "agent_id": sch.agent_id,
        "tool_mode": sch.tool_mode,
        # Only False is muted: a row from before migration 073 counts.
        "notify": getattr(sch, "notify", True) is not False,
    }
