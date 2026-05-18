"""Heartbeat scheduler: cron-triggered agent runs with per-schedule memory.

Architecture:
- A background coroutine in the tasks service wakes once per minute, queries
  enabled rows from tasks.schedules, and dispatches matching ones through
  the existing remote_executor pipeline.
- Per-schedule MEMORY.md lives on the agent VM at /agent/memory/<id>.md and
  is SCP'd into/out of each run's workdir (handled by remote_executor).
- secret_scrub redacts credentials at three layers: agent-side post-run,
  orchestrator-side rsync-back, and stream-level.

Pure-function entry points (`cron_matches_now`, `should_fire`) are unit-tested.
DB integration (`_tick_once`, `_create_task_from_schedule`, `_finalize_run`,
`schedule_tick_loop`) is covered by live e2e — see plan Task 9.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

logger = logging.getLogger("tasks.scheduler")


def cron_matches_now(cron_expr: str, tz: str, now_utc: datetime) -> bool:
    """True if `cron_expr` matches the current minute in `tz`.

    `croniter.match()` returns True iff the expression fires at the given
    timestamp (rounded to the minute). We convert `now_utc` into the
    schedule's local timezone so e.g. "0 20 * * *" + "Asia/Manila" fires
    at 8pm Manila time, not 8pm UTC.
    """
    local_now = now_utc.astimezone(ZoneInfo(tz))
    return croniter.match(cron_expr, local_now)


def should_fire(
    *,
    cron_expr: str,
    tz: str,
    last_run_at: datetime | None,
    now: datetime,
    enabled: bool,
) -> bool:
    """Decide whether this schedule should fire now.

    Rules (short-circuit, top-to-bottom):
      1. disabled → never fire
      2. cron does not match current minute → no
      3. last_run_at within the last 60s → no (dedupe — another tick already
         fired this minute, or a long-running tick is still racing)
      4. otherwise → fire
    """
    if not enabled:
        return False
    if not cron_matches_now(cron_expr, tz, now):
        return False
    if last_run_at is not None:
        if (now - last_run_at).total_seconds() < 60:
            return False
    return True


# ---------------------------------------------------------------------------
# DB integration. Below is *not* unit-tested locally because the tests would
# need a live Postgres connection — covered by the live e2e step (plan Task 9).
# ---------------------------------------------------------------------------
import uuid as _uuid

from sqlalchemy import select, update

from db import session
from models import Schedule, TaskItem
from secret_scrub import scrub

# Cap concurrent agent runs. Without this, if 10 schedules all fire at
# 20:00 the orchestrator spawns 10 simultaneous SSH+claude sessions and
# the 3.8GB Hetzner VM OOMs. 3 is a conservative bound; tune via env later.
_RUN_SEMAPHORE = asyncio.Semaphore(3)
_NULL_MEETING_UUID = _uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _create_task_from_schedule(sched: Schedule) -> TaskItem:
    """Build a TaskItem row from a Schedule and persist it.

    Schedules aren't tied to a meeting; we use the zero-UUID as a sentinel
    `meeting_id`. The persona is prepended as the system-message-equivalent
    prefix to the prompt body. The agent is reminded to read MEMORY.md
    (which remote_executor SCP's into the workdir before the run).
    """
    desc = (
        f"{sched.persona}\n\n"
        "---\n\n"
        f"Task: {sched.prompt}\n\n"
        "Memory protocol (IMPORTANT):\n"
        "- There is a file named `MEMORY.md` in your current working directory.\n"
        "- Before doing the task, use the Read tool on `./MEMORY.md` (no path prefix).\n"
        "- If the task is already done according to that file, output `SKIPPED: <reason>` and stop.\n"
        "- Otherwise, do the task, then use the Write tool to append a `## <ISO timestamp UTC>` section to `./MEMORY.md` summarising what you did (no secrets).\n"
        "- Do NOT use `/home/*/.claude/*` paths. Do NOT use Bash for file IO. Only `./MEMORY.md` via the Write/Edit/Read tools."
    )
    # Use a synthetic slug derived from schedule_id so the remote executor
    # has a per-schedule workdir to drop MEMORY.md into. UUIDs match the
    # _VALID_SLUG regex (lowercase hex + dashes), and prefixing with `sched-`
    # makes them obvious vs. user-built app slugs.
    sched_slug = f"sched-{str(sched.id)[:8]}"
    item = TaskItem(
        id=_uuid.uuid4(),
        meeting_id=_NULL_MEETING_UUID,
        action_type="BUILD",
        assignee_name=sched.user_email.split("@")[0],
        assignee_email=sched.user_email,
        description=desc,
        priority="NICE_TO_HAVE",
        status="pending",
        mode="ai",
        built_app_slug=sched_slug,
    )
    async with session() as s:
        s.add(item)
        await s.commit()
        await s.refresh(item)
    return item


async def _run_scheduled_task(sched: Schedule) -> str:
    """Dispatch to existing execution flow. Returns final status string.

    Bounded by _RUN_SEMAPHORE so a burst of schedules at the same minute
    can't OOM the orchestrator. Routes through routes_execution._run_execution
    (inline import to avoid an import cycle: routes_execution imports models,
    models is imported here at module-top).
    """
    async with _RUN_SEMAPHORE:
        item = await _create_task_from_schedule(sched)
        # Create a TaskExecution row so _run_execution has something to update.
        from models import TaskExecution
        async with session() as s:
            execution = TaskExecution(task_id=item.id, status="running", log="")
            s.add(execution)
            await s.commit()
            await s.refresh(execution)
        execution_id = execution.id
        from routes_execution import _run_execution
        try:
            await _run_execution(
                item.id, execution_id, sched.prompt, user_jwt=None,
                schedule_id=str(sched.id),
            )
        except Exception as exc:
            logger.exception("schedule %s run failed: %s", sched.id, scrub(str(exc)))
            return "failed"
        # Re-read the task's final status (set by _run_execution)
        async with session() as s:
            row = (await s.execute(
                select(TaskItem).where(TaskItem.id == item.id)
            )).scalar_one_or_none()
        return (row.status if row else None) or "unknown"


async def _finalize_run(sched: Schedule) -> None:
    """Background coroutine: run + record last_run_status."""
    status = await _run_scheduled_task(sched)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == sched.id).values(
                last_run_status=status,
            )
        )
        await s.commit()


async def _tick_once() -> None:
    """One pass of the scheduler. Reads enabled schedules, marks due ones
    as last_run_at=now BEFORE dispatching (so a slow run doesn't get
    re-fired by the next minute's tick), then kicks off background coros."""
    now = datetime.now(timezone.utc)
    async with session() as s:
        rows = (
            await s.execute(select(Schedule).where(Schedule.enabled.is_(True)))
        ).scalars().all()

    fire = [
        r for r in rows
        if should_fire(
            cron_expr=r.cron_expr,
            tz=r.tz,
            last_run_at=r.last_run_at,
            now=now,
            enabled=r.enabled,
        )
    ]
    if not fire:
        return

    logger.info("tick: %d schedule(s) firing", len(fire))
    for sched in fire:
        # Mark last_run_at IMMEDIATELY (pre-run) for dedupe. Even if the
        # run crashes, the next minute's tick won't double-fire the same
        # schedule. last_run_status will be updated by _finalize_run.
        async with session() as s:
            await s.execute(
                update(Schedule).where(Schedule.id == sched.id).values(
                    last_run_at=now,
                    last_run_status="running",
                )
            )
            await s.commit()
        asyncio.create_task(_finalize_run(sched))


async def schedule_tick_loop() -> None:
    """Main loop: wake once a minute, tick, sleep. Runs forever."""
    logger.info("schedule_tick_loop started")
    while True:
        try:
            await _tick_once()
        except Exception:
            logger.exception("schedule_tick failed")
        await asyncio.sleep(60)
