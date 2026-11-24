# -*- coding: utf-8 -*-
"""A cron output rings the red number only when it needs the person.

Measured 2026-11-24: the red number on Cron Jobs said 5 and none of the 5
needed anything. Three were Inbox checks that each began "Important first:
none. Nothing that needs a reply from you". Two things now decide whether a
new output counts (cron_quiet):

  - the agent marks a quiet answer, and that output arrives read;
  - a cron can be muted (migration 073), and its outputs arrive read.

A run that did not complete counts whatever the switch says, and a mark
the model left out counts too: the safe mistake is to ring.
"""
import inspect
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import cron_quiet as Q
import scheduler
import routes_schedules as R

HERE = pathlib.Path(__file__).parent
MIGRATION = HERE.parent / "migrations" / "073_schedule_notify.sql"
START = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=9)

QUIET_ANSWER = ("Important first: none. Nothing that needs a reply from you.\n\n"
                + Q.MARK)


# --- reading the mark ------------------------------------------------------

def test_a_marked_answer_is_quiet_and_the_mark_is_gone():
    text, quiet = Q.split(QUIET_ANSWER)
    assert quiet is True
    assert Q.MARK not in text
    assert text == "Important first: none. Nothing that needs a reply from you."


@pytest.mark.parametrize("line", [
    "`[[nothing-needs-you]]`", "**[[nothing-needs-you]]**",
    "- [[nothing-needs-you]]", "  [[NOTHING-NEEDS-YOU]].  ",
])
def test_the_mark_is_found_in_the_wrappers_models_add(line):
    text, quiet = Q.split("All quiet today.\n" + line)
    assert quiet is True
    assert text == "All quiet today."


def test_a_mark_inside_a_sentence_is_talk_about_it_not_the_mark():
    said = "I would normally add [[nothing-needs-you]] but a client wrote back."
    assert Q.split(said) == (said, False)


@pytest.mark.parametrize("answer", ["Two emails need a reply.", "", None])
def test_no_mark_counts_exactly_as_before(answer):
    assert Q.split(answer) == (answer, False)


def test_a_mark_followed_by_the_runners_notes_still_comes_out():
    """run_agent appends refusal notes after the model's answer, so the mark
    is not always the last line."""
    text, quiet = Q.split("Nothing new.\n" + Q.MARK + "\n\nOne tool was refused.")
    assert quiet is True
    assert Q.MARK not in text and "One tool was refused." in text


# --- what counts --------------------------------------------------------------

@pytest.mark.parametrize("status,quiet,notify,counts", [
    ("completed", False, True, True),      # an ordinary answer rings
    ("completed", True, True, False),      # a quiet one does not
    ("completed", False, False, False),    # a muted cron never does
    ("completed", False, None, True),      # a row from before 073 counts
    ("failed", True, True, True),          # a broken run always rings...
    ("failed", False, False, True),        # ...even on a muted cron
    ("refused", True, False, True),
])
def test_what_rings_the_red_number(status, quiet, notify, counts):
    assert Q.arrives_unread(status, quiet, notify) is counts


def test_the_ask_names_the_exact_mark_and_says_leave_it_out_when_unsure():
    assert Q.MARK in Q.ASK
    assert "not sure" in Q.ASK and "leave that line out" in Q.ASK


# --- the row the inbox reads ----------------------------------------------

class _Sched:
    def __init__(self, **kw):
        self.id = "11111111-2222-3333-4444-555555555555"
        self.user_email = "me@example.com"
        self.name = "Inbox check"
        self.agent_id = "agent.one"
        self.delivery_channel_id = kw.get("delivery_channel_id")
        self.delivery_platform = "discord"
        self.run_once = False
        if "notify" in kw:
            self.notify = kw["notify"]


def test_a_quiet_run_is_stored_read():
    v = scheduler.run_row(_Sched(), "completed", "x", START, END, quiet=True)
    assert v["unread"] is False


def test_an_ordinary_run_is_stored_unread():
    assert scheduler.run_row(_Sched(), "completed", "x", START, END)["unread"] is True


def test_a_muted_crons_run_is_stored_read_unless_it_broke():
    assert scheduler.run_row(_Sched(notify=False), "completed", "x",
                             START, END)["unread"] is False
    assert scheduler.run_row(_Sched(notify=False), "failed", "x",
                             START, END)["unread"] is True


def test_the_insert_writes_the_rows_unread_not_a_constant():
    src = " ".join(inspect.getsource(scheduler._record_run).split())
    assert ":result, :unread)" in src
    assert ":result, true)" not in src


# --- through _finalize_run ---------------------------------------------------

class _FakeSession:
    def __init__(self, writes):
        self.writes = writes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        try:
            self.writes.append(dict(stmt.compile().params))
        except Exception:                                   # noqa: BLE001
            self.writes.append({})

    async def commit(self):
        return None


@pytest.fixture
def running(monkeypatch):
    state = {"writes": [], "history": [], "delivered": [], "events": []}
    monkeypatch.setattr(scheduler, "session", lambda: _FakeSession(state["writes"]))

    async def _record(values):
        state["history"].append(values)

    async def _deliver(channel, platform, name, status, result, sid, extras=None):
        state["delivered"].append(result)

    monkeypatch.setattr(scheduler, "_record_run", _record)
    monkeypatch.setattr(scheduler, "_deliver_result", _deliver)
    monkeypatch.setattr(scheduler.events_out, "emit",
                        lambda *a, **k: state["events"].append(a))
    return state


async def test_a_quiet_answer_arrives_read_and_the_mark_reaches_nobody(running,
                                                                      monkeypatch):
    async def _ran(sched):
        return "completed", QUIET_ANSWER, {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched(delivery_channel_id="123"))

    row = running["history"][0]
    assert row["unread"] is False
    assert Q.MARK not in row["result"]
    stored = [w["last_result"] for w in running["writes"] if "last_result" in w]
    assert stored and Q.MARK not in stored[0], "the card would show the mark"
    assert running["delivered"] and Q.MARK not in running["delivered"][0]
    assert Q.MARK not in running["events"][0][2]["result"]


async def test_an_answer_with_news_still_rings(running, monkeypatch):
    async def _ran(sched):
        return "completed", "A client replied about the invoice.", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())
    assert running["history"][0]["unread"] is True


async def test_a_crash_on_a_muted_cron_still_rings(running, monkeypatch):
    async def _boom(sched):
        raise RuntimeError("the agent host went away")

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _boom)
    await scheduler._finalize_run(_Sched(notify=False))
    assert running["history"][0]["unread"] is True


# --- the switch ----------------------------------------------------------------

def test_the_migration_adds_the_switch_on_for_every_existing_cron():
    sql = MIGRATION.read_text(encoding="utf-8")
    code = " ".join(" ".join(l for l in sql.splitlines()
                             if not l.strip().startswith("--")).split())
    assert ("ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS notify "
            "BOOLEAN NOT NULL DEFAULT true") in code
    assert "UPDATE" not in code.upper()


def test_the_model_knows_the_switch():
    from models import Schedule
    col = Schedule.__table__.c.notify
    assert col.nullable is False
    assert col.default.arg is True


def test_the_list_says_whether_a_cron_is_muted():
    class Row:
        id = "x"; user_email = "e"; name = "n"; cron_expr = "0 9 * * *"
        tz = "UTC"; persona = ""; prompt = "p"; enabled = True
        last_run_at = None; last_run_status = None; last_result = None
        last_result_at = None; delivery_channel_id = None
        delivery_platform = "discord"; kind = "agent"; agent_id = None
        tool_mode = None
    assert R._serialize(Row())["notify"] is True, "no column yet means on"
    Row.notify = False
    assert R._serialize(Row())["notify"] is False


class _RouteSession:
    def __init__(self, seen):
        self.seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        self.seen.append((str(stmt), params))

    async def commit(self):
        return None


@pytest.fixture
def patched_route(monkeypatch):
    seen = []

    class S:
        id = "11111111-2222-3333-4444-555555555555"
        user_email = "me@example.com"

    async def _scoped(schedule_id, email):
        return S()

    monkeypatch.setattr(R, "_scoped_schedule", _scoped)
    monkeypatch.setattr(R, "session", lambda: _RouteSession(seen))
    return seen


async def test_muting_also_reads_what_that_cron_already_has_unread(patched_route):
    out = await R.update_schedule("11111111-2222-3333-4444-555555555555",
                                  R.UpdateScheduleIn(notify=False),
                                  x_cron_secret="", x_user_email="me@example.com",
                                  x_user_admin="")
    assert out == {"status": "updated"}
    sql = [" ".join(s.split()) for s, _ in patched_route]
    assert any("notify" in s for s in sql), "the switch was not written"
    marks = [(s, p) for s, p in patched_route if "SET unread = false" in s]
    assert marks, "muting left the red number where it was"
    stmt, params = marks[0]
    assert "CAST(:schedule_id AS UUID)" in stmt, "it must be this cron only"
    assert params == {"email": "me@example.com",
                      "schedule_id": "11111111-2222-3333-4444-555555555555"}


async def test_unmuting_reads_nothing(patched_route):
    await R.update_schedule("11111111-2222-3333-4444-555555555555",
                            R.UpdateScheduleIn(notify=True),
                            x_cron_secret="", x_user_email="me@example.com",
                            x_user_admin="")
    assert not [s for s, _ in patched_route if "SET unread" in s]
