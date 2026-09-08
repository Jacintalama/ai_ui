"""Whether an agent is working right now, and how long its last run took.

An agent is not a service that is up or down: it is asleep until something
asks it to do a thing. So there are three live states, not two. It is
WORKING while a run is actually in flight, AWAKE for a while after one
finishes, and IDLE once it has been left alone long enough. The middle one
exists because a card that said "Idle" one second after Ada answered a
question was answering the wrong question: nobody watching wants to know
whether a request is in flight this instant, they want to know whether the
agent they just spoke to is still with them.

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

#: How long after a run finishes an agent still counts as awake. Reset by
#: every new run, which needs no code: each turn writes its own row and the
#: card reads the newest one per agent, so talking to an agent moves the
#: clock by definition.
#:
#: Deliberately its own constant rather than a second use of
#: STALE_AFTER_CHANNEL, which happens to hold the same ten minutes today.
#: That one answers "how long may an unfinished run keep claiming to work
#: before we call it dead", which is a question about failure. This one
#: answers "how long does somebody still think of this agent as with them",
#: which is a question about attention. They are equal by coincidence, and
#: tying them together would move one the next time the other is tuned.
AWAKE_FOR = timedelta(minutes=10)

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
            # lie the card never recovers from.
            return {"state": "idle", "last_status": "failed",
                    "last_run_at": started.isoformat(),
                    "last_duration_seconds": None,
                    "source": row["source"]}
        return {"state": "working",
                "running_for_seconds": int(age.total_seconds()),
                "last_run_at": started.isoformat(),
                "source": row["source"]}

    # Measured from the END of the run, not the start: a twenty minute
    # schedule that finished a moment ago is as awake as a two second chat
    # turn, and off started_at it would be called idle the instant it
    # finished.
    #
    # Only a run that COMPLETED. Failed and waiting are drawn red because
    # they want a person, and ten minutes of green over the top of either
    # would hide the one thing on the card worth seeing.
    awake = (row["status"] == "completed" and now - finished <= AWAKE_FOR)
    return {"state": "awake" if awake else "idle",
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
