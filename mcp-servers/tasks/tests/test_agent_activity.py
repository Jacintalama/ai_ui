"""Is the agent working right now, and how long did the last one take?

The shaping is what the card reads, so it is tested directly rather than
through a database this environment does not have.
"""
from datetime import datetime, timedelta, timezone

import pytest

import agent_activity
from agent_activity import STALE_AFTER, _shape

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _row(started, finished=None, status=None, source="schedule"):
    return {"agent_id": "agent-x", "source": source, "started_at": started,
            "finished_at": finished, "status": status}


def test_a_run_in_flight_reads_as_working_with_its_elapsed_time():
    out = _shape(_row(NOW - timedelta(seconds=14)), NOW)
    assert out["state"] == "working"
    assert out["running_for_seconds"] == 14


def test_a_finished_run_reads_as_idle_with_how_long_it_took():
    out = _shape(_row(NOW - timedelta(seconds=30),
                      finished=NOW - timedelta(seconds=22),
                      status="completed"), NOW)
    assert out["state"] == "idle"
    assert out["last_status"] == "completed"
    assert out["last_duration_seconds"] == 8


def test_an_abandoned_run_is_not_shown_as_working_forever():
    """A process that dies mid run never writes its finish. Saying "working"
    for the rest of time is a lie the card can never recover from, and this
    codebase already wedged run-now once on exactly that."""
    out = _shape(_row(NOW - STALE_AFTER - timedelta(minutes=1)), NOW)
    assert out["state"] == "idle"
    assert out["last_status"] == "failed"


def test_a_slow_but_healthy_run_is_still_working():
    """The agent loop can legitimately take many minutes. The stale cut off
    has to sit above its worst case or a working agent gets called dead."""
    out = _shape(_row(NOW - STALE_AFTER + timedelta(minutes=1)), NOW)
    assert out["state"] == "working"


def test_the_stale_cut_off_clears_the_loops_own_worst_case():
    # MAX_TOOL_ITERATIONS completions of up to HTTP_TIMEOUT_SECONDS each.
    from agent_runner import HTTP_TIMEOUT_SECONDS, MAX_TOOL_ITERATIONS
    worst = timedelta(seconds=HTTP_TIMEOUT_SECONDS * MAX_TOOL_ITERATIONS)
    assert STALE_AFTER > worst, (
        "a healthy long run would be reported as failed")


def test_a_failed_run_says_so_rather_than_hiding_it():
    out = _shape(_row(NOW - timedelta(seconds=9),
                      finished=NOW - timedelta(seconds=1),
                      status="failed"), NOW)
    assert out["state"] == "idle"
    assert out["last_status"] == "failed"


def test_where_the_run_came_from_is_carried_through():
    """A run from a channel and a run from a schedule look identical without
    it, and "it ran when I mentioned it" is the useful half."""
    out = _shape(_row(NOW - timedelta(seconds=5), source="channel"), NOW)
    assert out["source"] == "channel"


def test_clock_skew_never_produces_a_negative_duration():
    out = _shape(_row(NOW, finished=NOW - timedelta(seconds=3),
                      status="completed"), NOW)
    assert out["last_duration_seconds"] == 0


async def test_recording_a_run_never_raises_when_the_database_is_down():
    """Bookkeeping must not be able to fail an agent run."""
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    original = agent_activity.session
    agent_activity.session = lambda: _Boom()
    try:
        assert await agent_activity.start_run("a", "me@example.com", "schedule") is None
        await agent_activity.finish_run("some-id", "completed")
        assert await agent_activity.activity_for("me@example.com") == {}
    finally:
        agent_activity.session = original


async def test_finishing_a_run_that_was_never_recorded_is_harmless():
    """start_run returns None when it could not write, and the caller passes
    that straight back in."""
    await agent_activity.finish_run(None, "completed")


async def test_activity_is_never_read_for_nobody():
    assert await agent_activity.activity_for("") == {}


async def test_the_endpoint_reads_activity_for_the_asking_user(monkeypatch):
    """One person's working agent is not another person's. An admin calling
    this must not be handed everyone's."""
    import routes_agents

    seen = {}

    async def fake(email):
        seen["email"] = email
        return {}

    class _User:
        email = "asker@example.com"

    monkeypatch.setattr(routes_agents.agent_activity, "activity_for", fake)
    await routes_agents.activity(user=_User())
    assert seen["email"] == "asker@example.com"
