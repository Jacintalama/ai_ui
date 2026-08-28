"""Whether an agent is working right now, and how long its last run took.

An agent is not a service that is up or down: it is asleep until something
asks it to do a thing. So "online" here means a run is in flight, and the
useful companion to that is how long the last one took, which is the only
honest signal that the thing is doing real work rather than nothing.

Recording is deliberately fire and forget. An agent run must never fail
because the bookkeeping around it failed, so every function here swallows its
own errors and the caller is not asked to handle them.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text as sql_text

from db import session

logger = logging.getLogger(__name__)

#: A run that has been unfinished longer than this is treated as failed
#: rather than as an agent that has been awake for hours. Derived from the
#: agent loop's own worst case (MAX_TOOL_ITERATIONS completions of up to
#: HTTP_TIMEOUT_SECONDS each, plus tool time) with room to spare, so a slow
#: but healthy run is never mislabelled.
STALE_AFTER = timedelta(minutes=45)

SOURCE_SCHEDULE = "schedule"
SOURCE_CHANNEL = "channel"


async def start_run(agent_id: str, user_email: str, source: str) -> str | None:
    """Record that an agent has started working. Returns the run id, or None.

    None means the bookkeeping failed, and the caller carries on regardless:
    the run itself matters, this does not.
    """
    if not agent_id or not user_email:
        return None
    run_id = str(uuid.uuid4())
    try:
        async with session() as s:
            await s.execute(
                sql_text(
                    "INSERT INTO tasks.agent_run "
                    "(id, agent_id, user_email, source, status) "
                    "VALUES (:id, :agent_id, :user_email, :source, 'running')"),
                {"id": run_id, "agent_id": agent_id,
                 "user_email": user_email, "source": source})
            await s.commit()
        return run_id
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the start of an agent run",
                       exc_info=True)
        return None


async def finish_run(run_id: str | None, status: str) -> None:
    """Close a run out. Safe to call with None, which is what start_run
    returns when it could not write."""
    if not run_id:
        return
    try:
        async with session() as s:
            await s.execute(
                sql_text(
                    "UPDATE tasks.agent_run "
                    "SET finished_at = now(), status = :status "
                    "WHERE id = :id"),
                {"id": run_id, "status": status})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the end of an agent run",
                       exc_info=True)


def _shape(row, now: datetime) -> dict:
    """One agent's activity, as the card needs to read it."""
    started = row["started_at"]
    finished = row["finished_at"]

    if finished is None:
        age = now - started
        if age > STALE_AFTER:
            # Nothing is going to close this row: whatever was running died
            # without writing its finish. Saying "working" forever would be a
            # lie the card never recovers from.
            return {"state": "idle", "last_status": "failed",
                    "last_run_at": started.isoformat(),
                    "last_duration_seconds": None,
                    "source": row["source"]}
        return {"state": "working",
                "running_for_seconds": int(age.total_seconds()),
                "last_run_at": started.isoformat(),
                "source": row["source"]}

    return {"state": "idle",
            "last_status": row["status"],
            "last_run_at": started.isoformat(),
            "last_duration_seconds": max(
                0, int((finished - started).total_seconds())),
            "source": row["source"]}


async def activity_for(user_email: str) -> dict:
    """The latest run of each of this person's agents, keyed by agent id.

    Scoped to the caller. One person's agent working is not another person's
    agent working, and an admin reading this must not see anyone else's.
    """
    if not user_email:
        return {}
    try:
        async with session() as s:
            rows = (await s.execute(
                sql_text(
                    "SELECT DISTINCT ON (agent_id) "
                    "  agent_id, source, started_at, finished_at, status "
                    "FROM tasks.agent_run "
                    "WHERE user_email = :email "
                    "ORDER BY agent_id, started_at DESC"),
                {"email": user_email})).mappings().all()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read agent activity", exc_info=True)
        return {}

    now = datetime.now(timezone.utc)
    return {r["agent_id"]: _shape(r, now) for r in rows}
