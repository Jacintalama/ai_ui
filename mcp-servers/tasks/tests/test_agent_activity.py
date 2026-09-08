"""Is the agent working right now, and how long did the last one take?

The shaping is what the card reads, so it is tested directly rather than
through a database this environment does not have.
"""
from datetime import datetime, timedelta, timezone

import pytest

import agent_activity
from agent_activity import (AWAKE_FOR, STALE_AFTER_CHANNEL,
                            STALE_AFTER_SCHEDULE, _shape)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _row(started, finished=None, status=None, source="schedule"):
    return {"agent_id": "agent-x", "source": source, "started_at": started,
            "finished_at": finished, "status": status}


def test_a_run_in_flight_reads_as_working_with_its_elapsed_time():
    out = _shape(_row(NOW - timedelta(seconds=14)), NOW)
    assert out["state"] == "working"
    assert out["running_for_seconds"] == 14


def test_a_finished_run_reads_as_awake_with_how_long_it_took():
    """Ralph asked for this looking at a card that said Idle one second after
    Ada answered him. An agent he just spoke to is not idle; it is awake and
    it stays awake for a while."""
    out = _shape(_row(NOW - timedelta(seconds=30),
                      finished=NOW - timedelta(seconds=22),
                      status="completed"), NOW)
    assert out["state"] == "awake"
    assert out["last_status"] == "completed"
    assert out["last_duration_seconds"] == 8


def test_an_agent_left_alone_long_enough_goes_idle():
    out = _shape(_row(NOW - AWAKE_FOR - timedelta(minutes=2),
                      finished=NOW - AWAKE_FOR - timedelta(minutes=1),
                      status="completed"), NOW)
    assert out["state"] == "idle"


def test_the_clock_runs_from_the_END_of_the_run_not_the_start():
    """A twenty minute scheduled run that finished a moment ago is awake. Off
    started_at it would be called idle the instant it finished, which is the
    bug being fixed, just harder to see."""
    out = _shape(_row(NOW - timedelta(minutes=20),
                      finished=NOW - timedelta(seconds=5),
                      status="completed"), NOW)
    assert out["state"] == "awake"


def test_talking_again_puts_it_back_to_awake():
    """The reset is not special code: each turn writes its own run row and the
    card reads the newest one. This pins that the newest row is all it takes,
    so nobody later adds a "first seen" field thinking one is needed."""
    stale = _shape(_row(NOW - AWAKE_FOR - timedelta(minutes=5),
                        finished=NOW - AWAKE_FOR - timedelta(minutes=4),
                        status="completed"), NOW)
    assert stale["state"] == "idle"
    fresh = _shape(_row(NOW - timedelta(seconds=3), finished=NOW,
                        status="completed"), NOW)
    assert fresh["state"] == "awake"


@pytest.mark.parametrize("status", ["failed", "waiting"])
def test_a_run_that_needs_a_person_never_reads_as_awake(status):
    """Failed and Needs approval are red because they want you. Ten minutes of
    green over the top of either would hide the one thing worth seeing."""
    out = _shape(_row(NOW - timedelta(seconds=30), finished=NOW,
                      status=status), NOW)
    assert out["state"] == "idle"
    assert out["last_status"] == status


def test_a_run_still_in_flight_is_working_not_merely_awake():
    """Working outranks awake: the pulse means it is thinking right now, and
    an in-flight run must not be flattened into "used recently"."""
    out = _shape(_row(NOW - timedelta(seconds=5)), NOW)
    assert out["state"] == "working"


def test_awake_is_the_ten_minutes_ralph_asked_for():
    assert AWAKE_FOR == timedelta(minutes=10)


@pytest.mark.parametrize("source,cut_off", [
    ("schedule", STALE_AFTER_SCHEDULE),
    ("channel", STALE_AFTER_CHANNEL),
])
def test_an_abandoned_run_is_not_shown_as_working_forever(source, cut_off):
    """A process that dies mid run never writes its finish. Saying "working"
    for the rest of time is a lie the card can never recover from, and this
    codebase already wedged run-now once on exactly that."""
    out = _shape(_row(NOW - cut_off - timedelta(minutes=1), source=source), NOW)
    assert out["state"] == "idle"
    assert out["last_status"] == "failed"


@pytest.mark.parametrize("source,cut_off", [
    ("schedule", STALE_AFTER_SCHEDULE),
    ("channel", STALE_AFTER_CHANNEL),
])
def test_a_slow_but_healthy_run_is_still_working(source, cut_off):
    """The agent loop can legitimately take many minutes. The stale cut off
    has to sit above its worst case or a working agent gets called dead."""
    out = _shape(_row(NOW - cut_off + timedelta(minutes=1), source=source), NOW)
    assert out["state"] == "working"


def test_a_chat_run_gives_up_sooner_than_a_scheduled_one():
    """Somebody is watching the card while a chat turn runs, and an agent
    still claiming to work ten minutes after they asked it something is not
    working. Nobody watches a schedule in real time."""
    assert STALE_AFTER_CHANNEL < STALE_AFTER_SCHEDULE
    at_eleven = NOW - timedelta(minutes=11)
    assert _shape(_row(at_eleven, source="channel"), NOW)["state"] == "idle"
    assert _shape(_row(at_eleven, source="schedule"), NOW)["state"] == "working"


def test_each_cut_off_clears_the_worst_case_of_its_own_path():
    """One number cannot be honest about both paths: a scheduled run may take
    twenty minutes of model time before a tool has run, while a chat turn is
    bounded at about three."""
    from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                              CHANNEL_MAX_TOOL_ITERATIONS,
                              HTTP_TIMEOUT_SECONDS, MAX_TOOL_ITERATIONS)
    worst_schedule = timedelta(
        seconds=HTTP_TIMEOUT_SECONDS * MAX_TOOL_ITERATIONS)
    worst_channel = timedelta(
        seconds=CHANNEL_HTTP_TIMEOUT_SECONDS * CHANNEL_MAX_TOOL_ITERATIONS)
    assert STALE_AFTER_SCHEDULE > worst_schedule, (
        "a healthy long schedule would be reported as failed")
    assert STALE_AFTER_CHANNEL > worst_channel, (
        "a healthy long chat turn would be reported as failed")


def test_an_unknown_source_is_treated_as_a_chat_run():
    """The shorter cut-off is the safer default for anything watched, and a
    source this module does not recognise is not a schedule."""
    out = _shape(_row(NOW - timedelta(minutes=11), source="something-new"), NOW)
    assert out["state"] == "idle"


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
