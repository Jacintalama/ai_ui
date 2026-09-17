"""Is the agent working right now, and how long did the last one take?

The shaping is what the card reads, so it is tested directly rather than
through a database this environment does not have.
"""
from datetime import datetime, timedelta, timezone

import pytest

import agent_activity
from agent_activity import (STALE_AFTER_CHANNEL, STALE_AFTER_SCHEDULE,
                            _shape)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _row(started, finished=None, status=None, source="schedule"):
    return {"agent_id": "agent-x", "source": source, "started_at": started,
            "finished_at": finished, "status": status}


def test_a_run_in_flight_reads_as_working_with_its_elapsed_time():
    out = _shape(_row(NOW - timedelta(seconds=14)), NOW)
    assert out["state"] == "working"
    assert out["running_for_seconds"] == 14


def test_a_finished_run_reads_as_ready():
    """Ralph: "fix the idle and active, it seems not accurate". It was
    accurate and it answered the wrong question. Ready is true whether it ran
    a second ago or last week, which is why it will stop feeling wrong."""
    out = _shape(_row(NOW - timedelta(seconds=30),
                      finished=NOW - timedelta(seconds=22),
                      status="completed"), NOW)
    assert out["state"] == "ready"
    assert out["last_duration_seconds"] == 8


def test_ready_does_not_go_stale():
    """The specific thing that felt wrong: an agent that worked perfectly an
    hour ago was reported as Idle, which reads as switched off."""
    old = _shape(_row(NOW - timedelta(days=3),
                      finished=NOW - timedelta(days=3), status="completed"), NOW)
    assert old["state"] == "ready"


def test_a_run_that_stopped_to_ask_needs_you():
    out = _shape(_row(NOW - timedelta(seconds=30), finished=NOW,
                      status="waiting"), NOW)
    assert out["state"] == "waiting"


def test_a_failed_run_reads_as_failed():
    out = _shape(_row(NOW - timedelta(seconds=30), finished=NOW,
                      status="failed"), NOW)
    assert out["state"] == "failed"


def test_a_run_in_flight_still_reads_as_working():
    assert _shape(_row(NOW - timedelta(seconds=5)), NOW)["state"] == "working"


def test_awake_is_gone():
    """Left behind, it would be two names for one thing and the page would
    have to handle both."""
    assert not hasattr(agent_activity, "AWAKE_FOR")
    for status in ("completed", "failed", "waiting"):
        out = _shape(_row(NOW - timedelta(seconds=9), finished=NOW,
                          status=status), NOW)
        assert out["state"] in ("ready", "failed", "waiting"), out


@pytest.mark.parametrize("status", ["failed", "waiting"])
def test_a_run_that_needs_a_person_reads_as_that_and_not_ready(status):
    """Failed and Needs you are drawn differently from Ready because they
    want a person, and hiding either behind a generic Ready would hide the
    one thing worth seeing."""
    out = _shape(_row(NOW - timedelta(seconds=30), finished=NOW,
                      status=status), NOW)
    assert out["state"] == status
    assert out["last_status"] == status


def test_a_run_still_in_flight_is_working_not_merely_ready():
    """Working outranks ready: the pulse means it is thinking right now, and
    an in-flight run must not be flattened into "used recently"."""
    out = _shape(_row(NOW - timedelta(seconds=5)), NOW)
    assert out["state"] == "working"


@pytest.mark.parametrize("source,cut_off", [
    ("schedule", STALE_AFTER_SCHEDULE),
    ("channel", STALE_AFTER_CHANNEL),
])
def test_an_abandoned_run_is_not_shown_as_working_forever(source, cut_off):
    """A process that dies mid run never writes its finish. Saying "working"
    for the rest of time is a lie the card can never recover from, and this
    codebase already wedged run-now once on exactly that."""
    out = _shape(_row(NOW - cut_off - timedelta(minutes=1), source=source), NOW)
    assert out["state"] == "failed"
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
    still claiming to work long after they asked it something is not
    working. Nobody watches a schedule in real time.

    Read off the constant rather than hardcoded. This said eleven minutes
    and would have failed on the deliberate move to twelve, which is a test
    breaking on a decision rather than catching a defect."""
    assert STALE_AFTER_CHANNEL < STALE_AFTER_SCHEDULE
    past_the_chat_window = NOW - STALE_AFTER_CHANNEL - timedelta(minutes=1)
    assert _shape(_row(past_the_chat_window, source="channel"),
                  NOW)["state"] == "failed"
    assert _shape(_row(past_the_chat_window, source="schedule"),
                  NOW)["state"] == "working"


def test_each_cut_off_clears_the_worst_case_of_its_own_path():
    """One number cannot be honest about both paths: a scheduled run may take
    twenty minutes of model time before a tool has run, while a chat turn is
    bounded at about three."""
    import agent_escalation
    from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                              CHANNEL_MAX_TOOL_ITERATIONS, FREE_MODELS,
                              FINAL_ROUND_MIN_TIMEOUT_SECONDS,
                              HTTP_TIMEOUT_SECONDS, MAX_TOOL_ITERATIONS)
    # An agent on a free model can spend the whole pool in one turn, and
    # each spent id costs one more failed completion of up to the full
    # timeout. The pool is consumed across the turn, not per round, so this
    # is an addition and not a multiplication.
    extra = len(FREE_MODELS) - 1

    def worst(rounds, timeout):
        # Written out here rather than read from worst_turn_seconds, so this
        # test cannot agree with a wrong formula by calling it. The two
        # shapes are moving to the paid model at the start (the free
        # attempts that decided it, then every round on paid) and moving at
        # the round cap (every free round and fallback id, then the paid
        # model's extra rounds). Both end in the write-up.
        paid = max(timeout, agent_escalation.PAID_TIMEOUT_SECONDS)
        write_up = max(paid, FINAL_ROUND_MIN_TIMEOUT_SECONDS)
        up_front = (1 + extra) * timeout + rounds * paid + write_up
        at_cap = ((rounds + extra) * timeout
                  + agent_escalation.PAID_EXTRA_ROUNDS * paid + write_up)
        return timedelta(seconds=max(up_front, at_cap)), timedelta(seconds=paid)

    worst_schedule, schedule_round = worst(MAX_TOOL_ITERATIONS,
                                           HTTP_TIMEOUT_SECONDS)
    worst_channel, channel_round = worst(CHANNEL_MAX_TOOL_ITERATIONS,
                                         CHANNEL_HTTP_TIMEOUT_SECONDS)
    # One round of headroom, not one second. Neither worst case counts tool
    # time between completions, so a window that clears the model time by
    # less than a round is not clearing anything. This is what the move from
    # forty five minutes to fifty bought: forty five cleared 2640 seconds by
    # sixty, which is a quarter of one round.
    assert STALE_AFTER_SCHEDULE > worst_schedule + schedule_round, (
        "a healthy long schedule would be reported as failed")
    # The channel clears its worst case by exactly one round and not a
    # second more: 660 plus 60 is 720, which is the twelve minute window. So
    # this one is >= where the schedule's is >, and that is deliberate.
    # Somebody is sitting at a keyboard here, and the only way to buy more
    # headroom is to make them wait longer for a turn that has already gone
    # wrong. Raising CHANNEL_MAX_TOOL_ITERATIONS or the pool means raising
    # the window with it; this assertion is what says so.
    assert STALE_AFTER_CHANNEL >= worst_channel + channel_round, (
        "a healthy long chat turn would be reported as failed")


def test_an_unknown_source_is_treated_as_a_chat_run():
    """The shorter cut-off is the safer default for anything watched, and a
    source this module does not recognise is not a schedule. Measured off
    the channel constant, so moving that window does not move this test."""
    out = _shape(_row(NOW - STALE_AFTER_CHANNEL - timedelta(minutes=1),
                      source="something-new"), NOW)
    assert out["state"] == "failed"


def test_a_failed_run_says_so_rather_than_hiding_it():
    out = _shape(_row(NOW - timedelta(seconds=9),
                      finished=NOW - timedelta(seconds=1),
                      status="failed"), NOW)
    assert out["state"] == "failed"
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
