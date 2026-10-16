"""The recorded past, shaped for the office: the log lines a page seeds
from, and the week of runs the history view draws.

Pure functions over rows shaped like tasks.agent_run and tasks.agent_step,
so no database is needed to hold them to what they claim.
"""
from datetime import datetime, timedelta, timezone

import agent_activity as act

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def _run(agent, started_ago, took=None, status="completed", source="channel"):
    started = NOW - timedelta(seconds=started_ago)
    return {"agent_id": agent, "source": source, "started_at": started,
            "finished_at": started + timedelta(seconds=took) if took is not None else None,
            "status": status if took is not None else None,
            "cost_usd": 0.012, "model": "gpt-5"}


def test_a_finished_run_is_two_lines_in_the_order_things_happened():
    lines = act._shape_events([_run("agent-ada", 100, took=30)], [], NOW)
    assert [l["text"] for l in lines] == ["completed", "started working from channel"]
    assert lines[0]["key"] == "ready" and lines[1]["key"] == "working"
    assert lines[0]["at"] > lines[1]["at"]


def test_an_open_run_is_one_line():
    lines = act._shape_events([_run("agent-ada", 10)], [], NOW)
    assert [l["text"] for l in lines] == ["started working from channel"]


def test_a_run_that_died_says_so():
    stale = act._stale_after("channel") + timedelta(minutes=1)
    lines = act._shape_events([_run("agent-ada", stale.total_seconds())], [], NOW)
    assert "never finished" in [l["text"] for l in lines]
    assert [l["key"] for l in lines if l["text"] == "never finished"] == ["failed"]


def test_a_waiting_run_and_a_failed_run_keep_their_own_words():
    lines = act._shape_events([_run("agent-ada", 100, took=5, status="waiting"),
                               _run("agent-mia", 200, took=5, status="failed")], [], NOW)
    texts = {(l["agent_id"], l["text"]): l["key"] for l in lines}
    assert texts[("agent-ada", "is waiting on you")] == "waiting"
    assert texts[("agent-mia", "failed")] == "failed"


def test_a_handoff_is_said_from_the_askers_side():
    step = {"agent_id": "agent-ada", "target_agent_id": "agent-mia",
            "status": "ok", "started_at": NOW - timedelta(seconds=5)}
    refused = {"agent_id": "agent-ada", "target_agent_id": "agent-rex",
               "status": "refused", "started_at": NOW - timedelta(seconds=3)}
    lines = act._shape_events([], [step, refused], NOW)
    assert [(l["text"], l["target_agent_id"], l["key"]) for l in lines] == [
        ("could not reach", "agent-rex", "failed"), ("asked", "agent-mia", "working")]


def test_a_handoff_with_no_colleague_draws_nothing():
    step = {"agent_id": "agent-ada", "target_agent_id": None,
            "status": "refused", "started_at": NOW}
    assert act._shape_events([], [step], NOW) == []


def test_newest_first_and_capped():
    runs = [_run("agent-ada", i * 10, took=1) for i in range(100)]
    lines = act._shape_events(runs, [], NOW)
    assert len(lines) == act.EVENTS_LIMIT
    assert lines == sorted(lines, key=lambda l: l["at"], reverse=True)


def test_a_history_row_carries_cost_duration_and_model():
    row = act._shape_history_row(_run("agent-ada", 100, took=30))
    assert row == {"agent_id": "agent-ada", "source": "channel", "status": "completed",
                   "started_at": (NOW - timedelta(seconds=100)).isoformat(),
                   "seconds": 30, "cost_usd": 0.012, "model": "gpt-5"}


def test_a_running_row_has_no_duration_and_says_running():
    row = act._shape_history_row(_run("agent-ada", 100))
    assert row["status"] == "running" and row["seconds"] is None


def test_spend_is_per_day_oldest_first():
    rows = [act._shape_history_row(_run("agent-ada", 0, took=1)),
            act._shape_history_row(_run("agent-ada", 86400 * 2, took=1)),
            act._shape_history_row(_run("agent-mia", 86400 * 2 + 5, took=1))]
    spend = act._spend_by_day(rows)
    assert [d["day"] for d in spend] == ["2026-10-14", "2026-10-16"]
    assert spend[0]["cost_usd"] == 0.024 and spend[1]["cost_usd"] == 0.012


def test_a_run_without_a_cost_adds_nothing():
    row = act._shape_history_row(dict(_run("agent-ada", 0, took=1), cost_usd=None))
    assert row["cost_usd"] is None
    assert act._spend_by_day([row]) == [{"day": "2026-10-16", "cost_usd": 0.0}]
