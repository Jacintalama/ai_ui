# -*- coding: utf-8 -*-
"""Every run of a schedule overwrote the one before it.

WHAT WAS THERE. `tasks.schedules` keeps `last_run_status`, `last_result`
and `last_result_at`: three columns describing the MOST RECENT run. Run
a schedule a hundred times and ninety-nine of those runs left no trace
at all. So there is no answer to "has this been failing all week", no
way to show more than one mark on a card, and nothing to alert on,
because an alert needs to know that this failure is the third in a row
rather than the first.

WHAT WAS ALREADY THERE, AND WHY IT IS NOT ENOUGH. `tasks.agent_run`
does record one row per run and has since migration 044, with
`source='schedule'` among its sources. Two things stop it answering this:
it carries no schedule id, so a run cannot be attributed to the schedule
that started it, and it is opened in `agent_runner.run_agent`, which a
video schedule and a schedule with no agent never reach. A card showing
seven marks has to show them for every kind of schedule, and the kind
that fails most often is precisely the one with no agent set.

WHERE THE ROW IS WRITTEN. `scheduler._finalize_run` is the one funnel
every run passes through, whatever kind it is, and it already writes
`last_run_status` on both the success path and the exception path. The
history row goes in the same two places, which is why the test that
matters most here is the one for the run that BLOWS UP: a crashed run is
exactly the run somebody will want the history of, and it is the easiest
one to forget.

FAIL OPEN, ALWAYS. A run must never fail because its bookkeeping did.
The same rule is written on `agent_activity.start_run`, which returns
None rather than raising, and it is asserted below by making the write
itself throw.

THE VALUES ARE A PURE FUNCTION, following `fire_values` directly above
it in the same module, so what gets stored is testable with no database,
no scheduler loop and no agent.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import scheduler

HERE = os.path.dirname(__file__)
MIGRATION = os.path.join(HERE, "..", "migrations", "071_schedule_run.sql")

START = datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=42)


class _Sched:
    def __init__(self, **kw):
        self.id = kw.get("id", "11111111-2222-3333-4444-555555555555")
        self.user_email = kw.get("user_email", "me@example.com")
        self.name = kw.get("name", "7pm quote")
        self.agent_id = kw.get("agent_id", "agent.one")
        self.delivery_channel_id = kw.get("delivery_channel_id")
        self.delivery_platform = kw.get("delivery_platform")
        self.run_once = kw.get("run_once", False)


# --- what gets stored, as a pure function ---------------------------------

def test_a_finished_run_becomes_a_row_naming_its_schedule_and_owner():
    v = scheduler.run_row(_Sched(), "completed", "Three headlines.",
                          START, END)
    assert str(v["schedule_id"]) == "11111111-2222-3333-4444-555555555555"
    assert v["user_email"] == "me@example.com"
    assert v["status"] == "completed"
    assert v["started_at"] == START
    assert v["finished_at"] == END


def test_the_result_goes_through_the_same_scrubbing_as_the_row():
    """Agent output can repeat a credential it was handed, and this lands
    in a database row and then on a page. `result_for_storage` already
    scrubs and caps; a second, laxer path to the same screen would undo
    it."""
    long = "x" * (scheduler.RESULT_LIMIT + 500)
    v = scheduler.run_row(_Sched(), "completed", long, START, END)
    assert len(v["result"]) <= len(scheduler.result_for_storage(long))
    assert v["result"] == scheduler.result_for_storage(long)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_a_run_that_said_nothing_stores_no_result(empty):
    """None rather than "", so a reader can tell "it produced nothing"
    from "it produced an empty answer"."""
    assert scheduler.run_row(_Sched(), "completed", empty,
                             START, END)["result"] is None


def test_a_failed_run_is_recorded_as_failed():
    v = scheduler.run_row(_Sched(), "failed", "it broke", START, END)
    assert v["status"] == "failed"


def test_a_history_row_is_never_still_running():
    """`running` is a state of the SCHEDULE, not of a finished run. A
    history row is written when a run is over, so storing `running` here
    would make a crashed run indistinguishable from a live one, which is
    the bug `last_run_status` already had: it wedged run-now permanently
    when a run died mid flight."""
    v = scheduler.run_row(_Sched(), "running", "", START, END)
    assert v["status"] != "running"
    assert v["status"] == "failed"


def test_a_run_with_no_owner_still_records_something():
    """A schedule whose owner was deleted still ran, and the run is still
    worth a row. Nothing here may raise."""
    v = scheduler.run_row(_Sched(user_email=None), "failed", None,
                          START, END)
    assert v["user_email"] == ""


def test_a_clock_that_went_backwards_does_not_make_a_negative_run():
    """finished_at before started_at is not information, it is a clock.
    Stored as equal rather than negative, so a duration never reads as
    minus four seconds on a card."""
    v = scheduler.run_row(_Sched(), "completed", "x", END, START)
    assert v["finished_at"] >= v["started_at"]


# --- that it is actually written, which is the defect shape ---------------

class _FakeSession:
    def __init__(self, captured):
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        try:
            self.captured.append(dict(stmt.compile().params))
        except Exception:                                   # noqa: BLE001
            self.captured.append({})

    async def commit(self):
        return None


@pytest.fixture
def running(monkeypatch):
    """Drive `_finalize_run` with the database and the run both faked."""
    state = {"writes": [], "history": [], "delivered": []}

    monkeypatch.setattr(scheduler, "session",
                        lambda: _FakeSession(state["writes"]))

    async def _record(values):
        state["history"].append(values)

    monkeypatch.setattr(scheduler, "_record_run", _record)
    monkeypatch.setattr(scheduler.events_out, "emit",
                        lambda *a, **k: None)
    return state


async def test_a_completed_run_is_written_to_the_history(running,
                                                         monkeypatch):
    async def _ran(sched):
        return "completed", "Three headlines.", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())

    assert len(running["history"]) == 1, "the run left no history row"
    row = running["history"][0]
    assert row["status"] == "completed"
    assert row["result"] == "Three headlines."


async def test_a_run_that_blows_up_is_still_written_to_the_history(
        running, monkeypatch):
    """The row somebody will actually go looking for. Before this, a
    crashed run set last_run_status='failed' and left nothing else, so
    the third crash in a row was indistinguishable from the first."""
    async def _boom(sched):
        raise RuntimeError("the agent host went away")

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _boom)
    await scheduler._finalize_run(_Sched())

    assert len(running["history"]) == 1, "a crashed run left no history row"
    assert running["history"][0]["status"] == "failed"


async def test_a_schedule_with_no_agent_is_recorded_like_any_other(
        running, monkeypatch):
    """The kind that fails most often, and the kind agent_run never sees
    because it never reaches agent_runner.run_agent."""
    async def _ran(sched):
        return "failed", scheduler.NO_AGENT, {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched(agent_id=None))

    assert len(running["history"]) == 1
    assert running["history"][0]["status"] == "failed"
    assert "no agent" in (running["history"][0]["result"] or "").lower()


async def test_bookkeeping_that_fails_never_fails_the_run(running,
                                                          monkeypatch):
    """A run must never fail because its history write did. Same rule as
    agent_activity.start_run, which returns None rather than raising."""
    async def _boom(values):
        raise RuntimeError("the history table is gone")

    monkeypatch.setattr(scheduler, "_record_run", _boom)

    async def _ran(sched):
        return "completed", "Three headlines.", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())  # must not raise

    stored = [w for w in running["writes"] if any("last_result" in k
                                                  for k in w)]
    assert stored, "the schedule's own row was skipped because history failed"


async def test_the_history_row_is_written_once_per_run(running,
                                                       monkeypatch):
    """Both paths write one, and only one. Writing on the success path
    and again in a finally would double every run."""
    async def _ran(sched):
        return "completed", "x", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())
    assert len(running["history"]) == 1


# --- the table ------------------------------------------------------------

def test_the_migration_exists_and_can_be_re_run():
    """db.py re-runs every migration on every startup, so anything here
    that is not idempotent breaks the next boot."""
    sql = open(MIGRATION, encoding="utf-8").read()
    assert "CREATE TABLE IF NOT EXISTS tasks.schedule_run" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql


def test_the_index_is_the_question_the_card_asks():
    """"the last seven runs of this schedule, newest first" is one index
    or it is a sort of every run ever recorded."""
    sql = open(MIGRATION, encoding="utf-8").read().lower()
    assert "schedule_id" in sql and "started_at desc" in sql


def test_deleting_a_schedule_takes_its_history_with_it():
    """Unlike agent_run, which deliberately has no foreign key because
    Open WebUI owns public.model and an agent can vanish at any moment.
    tasks.schedules is ours, and nothing reads the history of a schedule
    that no longer exists, so the rows should not outlive it."""
    sql = open(MIGRATION, encoding="utf-8").read().lower()
    assert "references tasks.schedules" in sql
    assert "on delete cascade" in sql


def test_the_shaped_row_says_what_a_card_needs():
    row = {"started_at": START, "finished_at": END, "status": "completed",
           "result": "Three headlines."}
    got = scheduler.shape_run(row)
    assert got["ok"] is True
    assert got["status"] == "completed"
    assert got["seconds"] == 42
    assert got["result"] == "Three headlines."


def test_a_failed_run_shapes_as_not_ok():
    row = {"started_at": START, "finished_at": END, "status": "failed",
           "result": None}
    assert scheduler.shape_run(row)["ok"] is False


def test_a_row_with_no_finish_is_not_counted_as_instant():
    """A process that dies mid run never writes the finish. agent_run's
    migration says readers must treat that as failed rather than as a run
    that has been awake for three days."""
    row = {"started_at": START, "finished_at": None, "status": None,
           "result": None}
    got = scheduler.shape_run(row)
    assert got["ok"] is False
    assert got["seconds"] is None
