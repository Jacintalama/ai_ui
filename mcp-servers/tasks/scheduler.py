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
