"""Whether an agent is working right now, and how long its last run took.

An agent is not a service that is up or down: it is asleep until something
asks it to do a thing. So a card asks two questions, not one. It is WORKING
while a run is actually in flight. Once a run has finished, it is READY,
whether that run ended a second ago or a week ago, unless the run itself
needs a person: WAITING when it stopped to ask something, FAILED when it did
not finish cleanly. There used to be a fourth state, AWAKE, for a while after
a run finished, so that a card did not say "Idle" one second after Ada
answered a question. It answered the wrong question: nobody watching wants to
know whether a request is in flight this instant, they want to know whether
the agent they just spoke to still works, which is true forever once it is
true at all.

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

#: A run unfinished longer than this is treated as failed rather than as an
#: agent that has been awake for hours. Two values, because the two paths
#: have very different worst cases and one number cannot be honest about
#: both.
#:
#: A chat turn is bounded by CHANNEL_MAX_TOOL_ITERATIONS (3) completions of
#: up to CHANNEL_HTTP_TIMEOUT_SECONDS (60) each, so roughly three minutes of
#: model time plus tool time. Ten minutes is comfortable room over that, and
#: it is what somebody watching the card actually wants: an agent that says
#: it is working ten minutes after they asked it something is not working.
STALE_AFTER_CHANNEL = timedelta(minutes=10)

#: A scheduled run uses MAX_TOOL_ITERATIONS (5) and HTTP_TIMEOUT_SECONDS
#: (240), so twenty minutes of model time alone is healthy before a single
#: tool has run. Ten minutes here would mark a working schedule as failed
#: while it was still going, which is this constant's own failure mode in
#: the other direction. Nobody is watching a schedule in real time, so the
#: cost of waiting is nothing.
STALE_AFTER_SCHEDULE = timedelta(minutes=45)

SOURCE_SCHEDULE = "schedule"
SOURCE_CHANNEL = "channel"


def _stale_after(source: str):
    """How long a run of this kind may go unfinished before it is a failure."""
    return (STALE_AFTER_SCHEDULE if source == SOURCE_SCHEDULE
            else STALE_AFTER_CHANNEL)


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
        if age > _stale_after(row["source"]):
            # Nothing is going to close this row: whatever was running died
            # without writing its finish. Saying "working" forever would be a
            # lie the card never recovers from, and so would falling through
            # to "ready": this row never finished, so it reads as the failure
            # it is.
            return {"state": "failed", "last_status": "failed",
                    "last_run_at": started.isoformat(),
                    "last_duration_seconds": None,
                    "source": row["source"]}
        return {"state": "working",
                "running_for_seconds": int(age.total_seconds()),
                "last_run_at": started.isoformat(),
                "source": row["source"]}

    # What somebody actually wants to know: is it doing something for me
    # right now, and did the last thing I asked for work. "Awake for ten
    # minutes" answered neither, which is why it felt wrong while being
    # perfectly accurate.
    status = row["status"]
    state = ("waiting" if status == "waiting"
             else "failed" if status == "failed"
             else "ready")
    return {"state": state,
            "last_status": status,
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
