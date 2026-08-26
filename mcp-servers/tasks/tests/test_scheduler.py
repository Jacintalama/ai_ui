"""Scheduler — pure-function tests for cron matching + should_fire dedupe,
plus the real agent_id dispatch branch in `_run_scheduled_task`."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Make the tasks/ dir importable when running tests directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import scheduler
from scheduler import cron_matches_now, should_fire

PH = ZoneInfo("Asia/Manila")


def test_cron_matches_at_20_00_PHT_not_at_20_00_UTC():
    pht_8pm = datetime(2026, 5, 18, 20, 0, 0, tzinfo=PH)
    assert cron_matches_now("0 20 * * *", "Asia/Manila", pht_8pm.astimezone(timezone.utc)) is True

    utc_8pm = datetime(2026, 5, 18, 20, 0, 0, tzinfo=timezone.utc)
    # In Manila that's 04:00 next day — does NOT match 0 20 * * *
    assert cron_matches_now("0 20 * * *", "Asia/Manila", utc_8pm) is False


def test_dedupe_within_same_minute():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    just_ran = datetime(2026, 5, 18, 12, 0, 5, tzinfo=timezone.utc)
    # last_run_at 25s ago, same minute → should NOT fire
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=just_ran, now=now, enabled=True) is False


def test_disabled_never_fires():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=None, now=now, enabled=False) is False


def test_enabled_first_run_fires_when_matched():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=None, now=now, enabled=True) is True


def test_enabled_last_run_old_enough_fires():
    now = datetime(2026, 5, 18, 12, 5, 30, tzinfo=timezone.utc)
    old = datetime(2026, 5, 18, 12, 4, 30, tzinfo=timezone.utc)  # 60s ago
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=old, now=now, enabled=True) is True


# --- _run_scheduled_task's agent_id dispatch branch --------------------------
#
# Every other test in this repo that names `_run_scheduled_task` replaces it
# wholesale with a stand-in (see test_run_now_bound.py, test_schedule_result.py,
# test_scheduler_delivery.py). That leaves the real dispatch branch — the
# `if getattr(sched, "agent_id", None):` check and the call it guards —
# completely unexercised: deleting it outright still leaves the rest of the
# suite green. These two call the real function.


async def test_run_scheduled_task_dispatches_to_the_agent_path(monkeypatch):
    """A schedule with an agent_id runs through agent_runner.run_agent, not
    the CLI executor."""
    run_agent = AsyncMock(return_value=("completed", "done", {}))
    monkeypatch.setattr("agent_runner.run_agent", run_agent)

    sched = SimpleNamespace(
        id="sched-agent-1", kind="agent", agent_id="agent-triage-0002",
        user_email="owner@example.com", name="Morning triage",
        prompt="Sort my unread mail.", last_result=None,
        last_run_status="completed",
    )

    status, result, extras = await scheduler._run_scheduled_task(sched)

    run_agent.assert_awaited_once_with(sched)
    assert (status, result, extras) == ("completed", "done", {})


async def test_run_scheduled_task_skips_the_agent_path_when_agent_id_is_null(
    monkeypatch,
):
    """A null agent_id is what every CLI executor schedule has always had,
    and must still take that path unchanged. Force the CLI branch to blow up
    on its first DB touch (there is no DB here) so a distinctive exception
    proves which branch actually ran, without needing a real database."""
    run_agent = AsyncMock(return_value=("completed", "done", {}))
    monkeypatch.setattr("agent_runner.run_agent", run_agent)

    class _TookTheCliPath(Exception):
        pass

    async def _boom(_sched):
        raise _TookTheCliPath()

    monkeypatch.setattr(scheduler, "_create_task_from_schedule", _boom)

    sched = SimpleNamespace(
        id="sched-cli-1", kind="agent", agent_id=None,
        user_email="owner@example.com", name="CLI schedule",
        prompt="Do the thing.", last_result=None, last_run_status="completed",
    )

    with pytest.raises(_TookTheCliPath):
        await scheduler._run_scheduled_task(sched)

    run_agent.assert_not_awaited()
