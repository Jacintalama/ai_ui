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


# A test asserting that a null agent_id takes the CLI executor path stood
# here. It passed for as long as it existed and it was describing a defect:
# that path built an app out of the prompt. The requirement inverted on
# 2026-09-23 and the case is covered below by
# test_a_schedule_with_no_agent_refuses_instead_of_building_an_app, which
# pins the same branch from the other side.


async def test_a_schedule_with_no_agent_refuses_instead_of_building_an_app(
    monkeypatch,
):
    """The CLI branch builds an APP out of the prompt. That was right when
    every schedule was an app build and is wrong for what people type.

    Measured on production 2026-09-23: two of the owner's enabled daily
    schedules, "give me the best quote for this day and send me news update
    today" and "give me the best qoute for today", had no agent. Every night
    at 7:00pm and 9:41pm each one spawned Claude Code against a synthetic
    slug, failed to build anything, and delivered "AutoFix could not resolve
    these load errors: - http: main response status 404 -" to his Discord,
    recorded as completed. 86 items rows going back to 2026-04-27 are the
    wreckage of the same path.

    Nothing can guess an app out of a sentence, so the run says what is
    missing and stops. It must not create a task: a row that exists is a row
    that shows on the App Builder page.
    """
    run_agent = AsyncMock(return_value=("completed", "done", {}))
    monkeypatch.setattr("agent_runner.run_agent", run_agent)

    made = []

    async def _made_a_task(_sched):
        made.append(_sched)
        raise AssertionError("a schedule with no agent must not create a task")

    monkeypatch.setattr(scheduler, "_create_task_from_schedule", _made_a_task)

    sched = SimpleNamespace(
        id="sched-no-agent", kind="agent", agent_id=None,
        user_email="owner@example.com", name="Daily quote",
        prompt="give me the best quote for today", last_result=None,
        last_run_status="completed",
    )

    status, result, extras = await scheduler._run_scheduled_task(sched)

    assert status == "failed"
    assert made == []
    run_agent.assert_not_awaited()
    # The owner reads this in Discord, so it has to say what to do about it.
    assert "agent" in result.lower()
    assert extras == {}
