# -*- coding: utf-8 -*-
"""A card still shows one run, because nothing reads the history.

WHAT SHIPPED AND WHAT DID NOT. Migration 071 and `scheduler._keep_run`
record every run, and `recent_runs` can read them back. Nothing calls
`recent_runs`. So the week is in the database and the card still draws
`last_run_status`, which is the single most recent run and the whole
reason the table was added. Half a feature reads as a whole one from the
commit log and as nothing at all from the page.

WHY THE WEEK TRAVELS WITH THE LIST, not a fetch per card. The page
already draws every card from one `GET /schedules` payload, and the
marks have to be on screen with the card rather than filling in after
it: the question being asked is "has this been failing all week", and an
answer that arrives late is read as "no". One query with a window
function serves every schedule the caller owns; a route per card is
seven round trips for a page that already made one.

WHY A GREEN MARK CARRIES NO TEXT. `result_for_storage` caps a result at
8000 characters. Seven runs of seven schedules is up to 392KB of result
text in a list payload, nearly all of it for runs that worked, and a run
that worked is not what anyone opens the card to read. A mark that is
not ok carries its reason, trimmed, because THAT is the question: the
live example is a daily schedule that has answered `refused` every
morning for weeks while the card showed one word and no cause.

TRIM ON THE WAY OUT, NOT ON THE WAY IN. The stored row keeps the full
8000 characters, because the result pane and any later alert both want
it. Only the list payload is trimmed, and it says when it cut, for the
same reason `result_for_storage` says it: showing the first 240
characters of something longer without a word is a lie about what
happened.

PURE, LIKE EVERYTHING ELSE IN THIS LAYER. `fire_values`, `run_row` and
`shape_run` are pure and tested with no database. `run_mark`,
`group_runs` and `with_runs` follow them, so the only untested part of
this change is two lines of wiring in the route, which is verified on
the server the way CLAUDE.md says to.
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import scheduler

SID = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"
START = datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=42)


def _row(**kw):
    return {"schedule_id": kw.get("schedule_id", SID),
            "started_at": kw.get("started_at", START),
            "finished_at": kw.get("finished_at", END),
            "status": kw.get("status", "completed"),
            "result": kw.get("result", "Three headlines.")}


# --- one mark on the card -------------------------------------------------

def test_a_mark_says_when_it_ran_whether_it_worked_and_how_long():
    got = scheduler.run_mark(scheduler.shape_run(_row()))
    assert got["ok"] is True
    assert got["status"] == "completed"
    assert got["seconds"] == 42
    assert got["at"] == START.isoformat()


def test_a_mark_that_worked_carries_no_result_text():
    """The payload cap, asserted. A green mark is drawn, never read."""
    got = scheduler.run_mark(scheduler.shape_run(_row(result="x" * 5000)))
    assert got.get("reason") is None
    assert "x" * 100 not in str(got)


def test_a_mark_that_did_not_work_carries_its_reason():
    got = scheduler.run_mark(scheduler.shape_run(
        _row(status="failed", result="OpenRouter answered 402: no credit.")))
    assert got["ok"] is False
    assert got["reason"] == "OpenRouter answered 402: no credit."


def test_a_refusal_carries_its_reason_because_that_is_the_whole_question():
    """The live case: a daily schedule asked to send an email while its
    agent is read-only answers `refused` every morning. The card showed
    the word and never the cause."""
    got = scheduler.run_mark(scheduler.shape_run(_row(
        status="refused",
        result="I cannot send email: this run is read-only.")))
    assert got["status"] == "refused"
    assert got["ok"] is False
    assert "read-only" in got["reason"]


def test_a_long_reason_is_trimmed_and_says_so():
    got = scheduler.run_mark(scheduler.shape_run(
        _row(status="failed", result="y" * 4000)))
    assert len(got["reason"]) < 400
    assert got["reason"].startswith("y" * 50)
    assert "truncated" in got["reason"].lower()


def test_a_short_reason_is_left_alone():
    got = scheduler.run_mark(scheduler.shape_run(
        _row(status="failed", result="Timed out after 600s.")))
    assert got["reason"] == "Timed out after 600s."
    assert "truncated" not in got["reason"].lower()


def test_a_failure_that_said_nothing_still_draws_a_mark():
    got = scheduler.run_mark(scheduler.shape_run(
        _row(status="failed", result=None)))
    assert got["ok"] is False
    assert got.get("reason") is None


def test_a_run_that_never_finished_is_not_ok_and_has_no_duration():
    got = scheduler.run_mark(scheduler.shape_run(
        _row(status="running", finished_at=None)))
    assert got["ok"] is False
    assert got["seconds"] is None


def test_a_mark_has_no_date_object_in_it():
    """It goes out as JSON from a route that does its own serializing, so a
    datetime here is a 500 at render time rather than a test failure."""
    got = scheduler.run_mark(scheduler.shape_run(_row()))
    assert all(not isinstance(v, datetime) for v in got.values())


# --- the week, grouped ----------------------------------------------------

def test_the_rows_are_grouped_by_schedule():
    rows = [_row(), _row(schedule_id=OTHER, status="failed")]
    got = scheduler.group_runs(rows)
    assert set(got) == {SID, OTHER}
    assert got[SID][0]["ok"] is True
    assert got[OTHER][0]["ok"] is False


def test_the_marks_stay_newest_first():
    rows = [_row(started_at=START),
            _row(started_at=START - timedelta(days=1)),
            _row(started_at=START - timedelta(days=2))]
    got = scheduler.group_runs(rows)[SID]
    assert [m["at"] for m in got] == [r["started_at"].isoformat()
                                      for r in rows]


def test_a_card_is_never_handed_more_marks_than_it_draws():
    """The query limits it. If the query ever stops limiting it, a daily
    schedule a year old must not put 365 marks in the payload."""
    rows = [_row(started_at=START - timedelta(days=n)) for n in range(40)]
    got = scheduler.group_runs(rows)[SID]
    assert len(got) == scheduler.RUN_HISTORY_SHOWN


def test_nothing_is_invented_for_a_schedule_that_never_ran():
    assert scheduler.group_runs([]) == {}


# --- what the list route hands the page -----------------------------------

def test_every_schedule_in_the_list_carries_its_own_week():
    rows = [{"id": SID, "name": "7pm quote"},
            {"id": OTHER, "name": "daily email summary"}]
    by_id = {SID: [{"ok": True}], OTHER: [{"ok": False}]}
    got = scheduler.with_runs(rows, by_id)
    assert got[0]["runs"] == [{"ok": True}]
    assert got[1]["runs"] == [{"ok": False}]


def test_a_schedule_with_no_history_says_so_with_an_empty_list():
    """Not a missing key. The page branches on `runs.length`, and
    `undefined.length` is a blank card, not a card saying no runs yet."""
    got = scheduler.with_runs([{"id": SID}], {})
    assert got[0]["runs"] == []


def test_attaching_the_week_changes_nothing_else_about_a_schedule():
    row = {"id": SID, "name": "7pm quote", "enabled": True,
           "last_run_status": "completed"}
    got = scheduler.with_runs([dict(row)], {SID: [{"ok": True}]})[0]
    assert {k: v for k, v in got.items() if k != "runs"} == row


def test_the_rows_handed_in_are_not_mutated():
    """`_serialize` output is handed around; attaching must not reach back
    into a caller's dict."""
    rows = [{"id": SID, "name": "7pm quote"}]
    scheduler.with_runs(rows, {SID: [{"ok": True}]})
    assert "runs" not in rows[0]
