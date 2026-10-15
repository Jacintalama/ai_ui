"""The records behind an agent team job: one job, its numbered steps.

A job is a request to the whole team that the lead agent split into steps,
each for one agent. It is proposed (a plan card in the chat), started by the
person, run one step at a time by the background worker, and closed by the
lead's final answer. See docs/plans/2026-10-14-agent-team-jobs-design.md.

Unlike agent_activity, nothing here swallows its own errors. agent_activity
is bookkeeping beside a run that matters more than it does; these rows ARE
the run. A worker that believed a step was claimed, finished or requeued
when the write had failed would run a step twice or lose one, so every
function raises and the caller decides what failing open means for it.

Every read and write that answers a person is scoped to that person. The
two that are not, claim_next_step and recover_after_restart, are the
worker's, and look across everyone because the worker serves everyone.
"""
import logging
import uuid

from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError

from agent_activity import SOURCE_JOB, STEP_FAILED, STEP_OK
from db import session

logger = logging.getLogger(__name__)

#: A plan nobody started within a day is stale: the person has moved on, and
#: the files or facts it was planned against may have too. Starting it then
#: would run yesterday's plan as if it were today's.
PROPOSAL_TTL_HOURS = 24

#: What a step's result may hold. The brief cuts each earlier result to about
#: 2,000 characters before an agent sees it, so this is not about the model:
#: it keeps one runaway answer from making a row, and every card that reads
#: it, as large as the answer was.
RESULT_MAX_CHARS = 20000

#: What a job's request may hold. The request is the person's message, which
#: has no limit of its own, and it rides into every step's brief, the lead's
#: closing brief, the card and the room's title. A pasted document becomes a
#: plan's request in full otherwise, and every one of those as large as it.
REQUEST_MAX_CHARS = 4000

#: A first try and one retry. Most failures are a busy free model or a
#: transient error, which a second try gets past; one that fails twice is not
#: going to work on a third, and the person should hear why. A restart that
#: cuts a step off counts as the attempt it was, so a step that kills the
#: process cannot run forever across restarts (recover_after_restart).
MAX_ATTEMPTS = 2

#: Why recover_after_restart ended a job, for the note the worker posts.
#: The step was cut off on its last attempt.
WHY_INTERRUPTED = "interrupted"
#: The step was cut off after its turn had already run a tool.
WHY_ACTED = "acted"

_JOB_COLUMNS = ("id, user_email, chat_id, lead_agent_id, request, status, "
                "result, seen, created_at, started_at, finished_at")
_STEP_COLUMNS = "id, job_id, position, agent_id, task, status, attempts, " \
                "result, run_id"


def _cap(result: str | None) -> str | None:
    if result is None:
        return None
    return result[:RESULT_MAX_CHARS]


async def create_proposed(user_email: str, chat_id: str | None,
                          lead_agent_id: str, request: str,
                          steps: list[dict]) -> str:
    """Write a proposed job and its waiting steps. Returns the job id.

    One transaction: a plan card whose steps were not saved would draw an
    empty plan, and Start would run a job with nothing in it.
    """
    job_id = str(uuid.uuid4())
    async with session() as s:
        await s.execute(
            sql_text(
                "INSERT INTO tasks.agent_job "
                "(id, user_email, chat_id, lead_agent_id, request) "
                "VALUES (:id, :email, :chat_id, :lead, :request)"),
            {"id": job_id, "email": user_email, "chat_id": chat_id,
             "lead": lead_agent_id,
             "request": (request or "")[:REQUEST_MAX_CHARS]})
        for position, step in enumerate(steps, start=1):
            await s.execute(
                sql_text(
                    "INSERT INTO tasks.agent_job_step "
                    "(id, job_id, position, agent_id, task) "
                    "VALUES (:id, :job_id, :position, :agent_id, :task)"),
                {"id": str(uuid.uuid4()), "job_id": job_id,
                 "position": position, "agent_id": step["agent_id"],
                 "task": step["task"]})
        await s.commit()
    return job_id


async def _read(s, job_id: str, user_email: str | None) -> dict | None:
    where = "id = :id"
    params = {"id": job_id}
    if user_email is not None:
        where += " AND user_email = :email"
        params["email"] = user_email
    row = (await s.execute(
        sql_text("SELECT %s FROM tasks.agent_job WHERE %s"
                 % (_JOB_COLUMNS, where)), params)).mappings().first()
    if row is None:
        return None
    steps = (await s.execute(
        sql_text("SELECT %s FROM tasks.agent_job_step WHERE job_id = :id "
                 "ORDER BY position" % _STEP_COLUMNS),
        {"id": job_id})).mappings().all()
    job = dict(row)
    job["steps"] = [dict(r) for r in steps]
    return job


async def get(job_id: str) -> dict | None:
    """The job with its steps in order, for the worker. Not owner-checked:
    nothing a person sends reaches this; use for_owner for that."""
    async with session() as s:
        return await _read(s, job_id, None)


async def for_owner(job_id: str, user_email: str) -> dict | None:
    """The job, only if it is this person's. Another person's id reads as
    no job at all, so a guessed id learns nothing."""
    async with session() as s:
        return await _read(s, job_id, user_email)


async def start(job_id: str, user_email: str) -> bool:
    """Proposed -> running, for its owner, while the plan is fresh.

    False, never an error, for every reason a Start can be refused: not the
    owner, not proposed any more, older than a day, or the person already
    has a job running or waiting on them (the unique index says so, and it
    is the index rather than a read-then-write that decides, so two quick
    Starts cannot both win).
    """
    try:
        async with session() as s:
            result = await s.execute(
                sql_text(
                    "UPDATE tasks.agent_job "
                    "SET status = 'running', started_at = now() "
                    "WHERE id = :id AND user_email = :email "
                    "  AND status = 'proposed' "
                    "  AND created_at > now() - make_interval(hours => :ttl) "
                    "RETURNING id"),
                {"id": job_id, "email": user_email,
                 "ttl": PROPOSAL_TTL_HOURS})
            started = result.first() is not None
            await s.commit()
        return started
    except IntegrityError:
        logger.info("job %s not started: its owner already has one running",
                    job_id)
        return False


async def cancel(job_id: str, user_email: str) -> bool:
    """Stop a job that has not ended: it is cancelled and every step not yet
    finished is skipped. False when it is not this person's or is already
    over. Cancelling the asyncio task running a step is the worker's part."""
    async with session() as s:
        result = await s.execute(
            sql_text(
                "UPDATE tasks.agent_job "
                "SET status = 'cancelled', finished_at = now() "
                "WHERE id = :id AND user_email = :email "
                "  AND status IN ('proposed', 'running', 'needs_you') "
                "RETURNING id"),
            {"id": job_id, "email": user_email})
        cancelled = result.first() is not None
        if cancelled:
            await _skip_unfinished(s, job_id)
        await s.commit()
    return cancelled


async def _skip_unfinished(s, job_id: str) -> None:
    await s.execute(
        sql_text(
            "UPDATE tasks.agent_job_step SET status = 'skipped' "
            "WHERE job_id = :id AND status IN ('waiting', 'running')"),
        {"id": job_id})


async def set_status(job_id: str, status: str,
                     result: str | None = None) -> bool:
    """Move a live job on: to needs_you and back to running, or to an end.

    Only a job that is still running or waiting on the person moves. A job
    the person stopped while its last step was finishing must stay
    cancelled, not be overwritten as done by the worker a moment later.

    done, failed and cancelled set finished_at; failed and cancelled also
    skip the steps that will now never run, so the card does not show them
    as still to come.
    """
    ending = status in ("done", "failed", "cancelled")
    async with session() as s:
        res = await s.execute(
            sql_text(
                "UPDATE tasks.agent_job "
                "SET status = :status, "
                "    result = COALESCE(:result, result), "
                "    finished_at = CASE WHEN :ending THEN now() "
                "                       ELSE finished_at END "
                "WHERE id = :id AND status IN ('running', 'needs_you') "
                "RETURNING id"),
            {"id": job_id, "status": status, "result": _cap(result),
             "ending": ending})
        moved = res.first() is not None
        if moved and status in ("failed", "cancelled"):
            await s.execute(
                sql_text(
                    "UPDATE tasks.agent_job_step SET status = 'skipped' "
                    "WHERE job_id = :id AND status = 'waiting'"),
                {"id": job_id})
        await s.commit()
    return moved


async def claim_next_step() -> dict | None:
    """Take the next step to run, or None when there is nothing to do.

    The next step is the lowest waiting position of the oldest running job
    that has no step running already: a job's steps run one at a time,
    because each one is briefed with the results of the steps before it.
    The step is flipped to running with its attempt counted in the same
    transaction, and returned with its job (steps included).

    Two workers must never take the same step, or one job's two steps at
    once. The job row is the lock: FOR UPDATE SKIP LOCKED means a second
    claimer passes over a job the first is claiming from. Holding that lock,
    a fresh statement then checks again that no step of the job is running,
    because the first query's snapshot may predate a claim that committed
    while this one waited for the row.
    """
    async with session() as s:
        job_row = (await s.execute(
            sql_text(
                "SELECT j.id FROM tasks.agent_job j "
                "WHERE j.status = 'running' "
                "  AND EXISTS (SELECT 1 FROM tasks.agent_job_step w "
                "              WHERE w.job_id = j.id AND w.status = 'waiting') "
                "  AND NOT EXISTS (SELECT 1 FROM tasks.agent_job_step r "
                "                  WHERE r.job_id = j.id "
                "                    AND r.status = 'running') "
                "ORDER BY j.started_at, j.created_at "
                "LIMIT 1 "
                "FOR UPDATE OF j SKIP LOCKED"))).first()
        if job_row is None:
            await s.rollback()
            return None
        job_id = job_row[0]
        busy = (await s.execute(
            sql_text("SELECT 1 FROM tasks.agent_job_step "
                     "WHERE job_id = :id AND status = 'running' LIMIT 1"),
            {"id": job_id})).first()
        if busy is not None:
            # Lost the race described above. The other claimer has this
            # job's step; the next poll finds the next job.
            await s.rollback()
            return None
        step = (await s.execute(
            sql_text(
                "UPDATE tasks.agent_job_step "
                "SET status = 'running', attempts = attempts + 1, "
                "    started_at = now() "
                "WHERE id = (SELECT id FROM tasks.agent_job_step "
                "            WHERE job_id = :id AND status = 'waiting' "
                "            ORDER BY position LIMIT 1) "
                "RETURNING %s" % _STEP_COLUMNS),
            {"id": job_id})).mappings().first()
        if step is None:
            await s.rollback()
            return None
        claimed = dict(step)
        claimed["job"] = await _read(s, job_id, None)
        await s.commit()
    return claimed


async def finish_step(step_id: str, status: str, result: str | None = None,
                      run_id: str | None = None) -> bool:
    """Close a running step as done or failed, with its answer and run.

    Only a running step closes. One the person stopped was skipped by the
    Stop, and an answer that arrives after it must not bring it back.
    """
    async with session() as s:
        res = await s.execute(
            sql_text(
                "UPDATE tasks.agent_job_step "
                "SET status = :status, result = :result, "
                "    run_id = COALESCE(:run_id, run_id) "
                "WHERE id = :id AND status = 'running' RETURNING id"),
            {"id": step_id, "status": status, "result": _cap(result),
             "run_id": run_id})
        closed = res.first() is not None
        await s.commit()
    return closed


async def requeue_step(step_id: str) -> None:
    """Running -> waiting, so the next claim runs it again. Its attempt
    stays counted: that count is what stops a step retrying forever."""
    async with session() as s:
        await s.execute(
            sql_text("UPDATE tasks.agent_job_step SET status = 'waiting' "
                     "WHERE id = :id AND status = 'running'"),
            {"id": step_id})
        await s.commit()


def _acted_sql(st: str, j: str) -> str:
    """SQL true when the step `st` of job `j` has, in its current attempt,
    run a tool: a tool step that ran (ok) or ran and failed (and so may have
    done part of something) in a run of that agent, for that person, from a
    job, started since the step was claimed.

    Matched by owner, agent, source and time rather than by run id, because
    the run id is not known until the turn returns, and a restart is exactly
    the case where it never returns. One job per person runs at a time and
    its steps one after another, so a job run of this agent for this person
    since the claim is this step's. A tool held for a yes or refused did not
    run. A colleague asked from the step runs under its own run (source
    colleague) and is not counted; asking it is, under the step's run.
    """
    return ("EXISTS (SELECT 1 FROM tasks.agent_step a "
            "        JOIN tasks.agent_run r ON r.id = a.run_id "
            "        WHERE r.user_email = %(j)s.user_email "
            "          AND r.agent_id = %(st)s.agent_id "
            "          AND r.source = :job_source "
            "          AND r.started_at >= COALESCE(%(st)s.started_at, "
            "                                       %(j)s.started_at) "
            "          AND a.status IN (:step_ok, :step_failed))"
            % {"st": st, "j": j})


_ACTED_PARAMS = {"job_source": SOURCE_JOB, "step_ok": STEP_OK,
                 "step_failed": STEP_FAILED}


async def step_acted(step_id: str) -> bool:
    """Whether this step's current attempt already ran a tool.

    A step that did must not run again, on a retry or after a restart: its
    tool may have sent the email, and a second run sends it again. A tool
    killed mid-call before its row was written cannot be seen here, and
    neither can one whose run row could not be written (agent_activity
    swallows its own errors); both are rarer than the retry this guards.
    """
    async with session() as s:
        row = (await s.execute(
            sql_text("SELECT " + _acted_sql("st", "j") + " "
                     "FROM tasks.agent_job_step st "
                     "JOIN tasks.agent_job j ON j.id = st.job_id "
                     "WHERE st.id = :id"),
            dict(_ACTED_PARAMS, id=step_id))).first()
    return bool(row and row[0])


async def recover_after_restart() -> dict:
    """Tidy up after the service stopped mid-job.

    Returns {"requeued": n, "ended": [...]}: how many steps go round again,
    and one entry per job this ended, for the worker to tell its owner
    (job_id, user_email, lead_agent_id, request, status, why, and the
    agent_id and position of the step that ended it).

    A step left running by a job that is still running was lost with the
    process. It goes back to waiting and runs again, its lost attempt still
    counted, unless running it again is wrong:
    - it has used its attempts (MAX_ATTEMPTS): a step that takes the process
      down with it would otherwise do so on every start, forever;
    - its turn already ran a tool (step_acted): running it again would do
      that again.
    Either way the step fails and its job with it, the rest skipped.

    A step whose job is waiting on the person (needs_you) was not lost: it
    is held for their Yes or No, which is saved with the chat and finishes
    it, so it is left alone. A plan nobody started in a day is cancelled, so
    the badge and the card stop offering it.
    """
    ended = []
    async with session() as s:
        lost = (await s.execute(
            sql_text(
                "SELECT st.id, st.job_id, st.agent_id, st.position, "
                "       st.attempts, j.user_email, j.lead_agent_id, "
                "       j.request, " + _acted_sql("st", "j") + " AS acted "
                "FROM tasks.agent_job_step st "
                "JOIN tasks.agent_job j ON j.id = st.job_id "
                "WHERE st.status = 'running' AND j.status = 'running' "
                "FOR UPDATE OF st, j"),
            _ACTED_PARAMS)).mappings().all()
        requeue = []
        for row in lost:
            if row["attempts"] < MAX_ATTEMPTS and not row["acted"]:
                requeue.append(row["id"])
                continue
            why = WHY_ACTED if row["acted"] else WHY_INTERRUPTED
            await s.execute(
                sql_text("UPDATE tasks.agent_job_step "
                         "SET status = 'failed', result = :why "
                         "WHERE id = :id"),
                {"id": row["id"], "why": why})
            await s.execute(
                sql_text("UPDATE tasks.agent_job "
                         "SET status = 'failed', finished_at = now() "
                         "WHERE id = :id"),
                {"id": row["job_id"]})
            await _skip_unfinished(s, row["job_id"])
            ended.append({"job_id": row["job_id"],
                          "user_email": row["user_email"],
                          "lead_agent_id": row["lead_agent_id"],
                          "request": row["request"], "status": "failed",
                          "why": why, "agent_id": row["agent_id"],
                          "position": row["position"]})
        if requeue:
            await s.execute(
                sql_text("UPDATE tasks.agent_job_step SET status = 'waiting' "
                         "WHERE id = ANY(:ids)"),
                {"ids": requeue})
        await s.execute(
            sql_text(
                "UPDATE tasks.agent_job "
                "SET status = 'cancelled', finished_at = now() "
                "WHERE status = 'proposed' "
                "  AND created_at <= now() - make_interval(hours => :ttl)"),
            {"ttl": PROPOSAL_TTL_HOURS})
        await s.commit()
    if requeue or ended:
        logger.info("after a restart: requeued %d agent job steps, ended %d "
                    "jobs", len(requeue), len(ended))
    return {"requeued": len(requeue), "ended": ended}


async def unseen_count(user_email: str) -> int:
    """How many of this person's jobs ended since they last looked: the
    number on the Done badge. A job they cancelled themselves is not news."""
    async with session() as s:
        n = (await s.execute(
            sql_text(
                "SELECT count(*) FROM tasks.agent_job "
                "WHERE user_email = :email AND seen = FALSE "
                "  AND status IN ('done', 'failed')"),
            {"email": user_email})).scalar()
    return int(n or 0)


async def mark_seen(user_email: str) -> None:
    async with session() as s:
        await s.execute(
            sql_text(
                "UPDATE tasks.agent_job SET seen = TRUE "
                "WHERE user_email = :email AND seen = FALSE "
                "  AND status IN ('done', 'failed')"),
            {"email": user_email})
        await s.commit()


async def jobs_for_chat(user_email: str, chat_id: str | None) -> dict:
    """{job_id: summary} for the plan cards in one conversation.

    A summary is what a card's status line needs and nothing else: the
    job's status, how many steps are done out of how many, and which agent
    holds the running step (None when none does).
    """
    async with session() as s:
        rows = (await s.execute(
            sql_text(
                "SELECT j.id, j.status, "
                "  count(st.id) FILTER (WHERE st.status = 'done') AS done, "
                "  count(st.id) AS total, "
                "  (SELECT r.agent_id FROM tasks.agent_job_step r "
                "   WHERE r.job_id = j.id AND r.status = 'running' "
                "   ORDER BY r.position LIMIT 1) AS current_agent_id "
                "FROM tasks.agent_job j "
                "LEFT JOIN tasks.agent_job_step st ON st.job_id = j.id "
                "WHERE j.user_email = :email "
                "  AND j.chat_id IS NOT DISTINCT FROM :chat_id "
                "GROUP BY j.id, j.status"),
            {"email": user_email, "chat_id": chat_id})).mappings().all()
    return {r["id"]: {"status": r["status"], "done": int(r["done"]),
                      "total": int(r["total"]),
                      "current_agent_id": r["current_agent_id"]}
            for r in rows}
