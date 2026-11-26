# -*- coding: utf-8 -*-
"""A cron job can email its answer to the person who owns it.

Measured 2026-11-26: the only cron runs that failed in two weeks were jobs
asked to email their summary ("Daily email summary", refused 5 of its last 6
mornings). A schedule runs read only unless its agent is set to act on its
own everywhere, so "email me a summary" could never work, and the main chat
still said "Set up. Every Friday at 4pm you will get an email". Live test:
Run now, refused after 29 seconds, the summary only in Cron outputs.

Emailing yourself the answer is delivery, not an action: the platform sends
the finished answer to the person's own connected Gmail, the agent only
writes it and is told not to send it, and nobody's access is widened.
"""
import os
import pathlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import agent_memory  # noqa: E402
import agent_runner  # noqa: E402
import cron_email as E  # noqa: E402
import routes_schedules as R  # noqa: E402
import scheduler  # noqa: E402

HERE = pathlib.Path(__file__).parent
MIGRATION = HERE.parent / "migrations" / "074_schedule_email_me.sql"
WHEN = datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc)


# --- what the email says -----------------------------------------------------

def test_the_subject_is_the_jobs_name_and_says_when_it_did_not_finish():
    assert E.subject_for("Weekly unread Gmail digest", "completed") == \
        "Weekly unread Gmail digest"
    bad = E.subject_for("Weekly unread Gmail digest", "failed")
    assert bad.startswith("Weekly unread Gmail digest") and "did not finish" in bad


def test_the_body_is_plain_text_without_markdown_marks():
    body = E.body_for("Inbox check", "**Nothing new** today.\n\n## Later\n- one\n- `two`")
    assert "**" not in body and "## " not in body and "`" not in body
    assert "Nothing new today." in body
    assert "- one" in body, "a list stays a list"


def test_the_body_says_where_it_came_from_and_how_to_stop_it():
    body = E.body_for("Inbox check", "All quiet.")
    assert '"Inbox check"' in body
    assert "/cronjobs" in body, "the way to change or stop it"


def test_a_long_answer_is_cut_and_says_so():
    body = E.body_for("Big", "x" * (E.MAX_BODY + 500))
    assert len(body) < E.MAX_BODY + 400
    assert "cut" in body.lower()


# --- sending -----------------------------------------------------------------

@pytest.fixture
def gmail(monkeypatch):
    calls = {"get": [], "post": []}
    state = {"status": {"connected": True, "account": "me@gmail.example"},
             "sent": {"success": True, "message_id": "m1"}}

    async def _get(path, user_email):
        calls["get"].append((path, user_email))
        if isinstance(state["status"], Exception):
            raise state["status"]
        return state["status"]

    async def _post(path, user_email, body):
        calls["post"].append((path, user_email, body))
        if isinstance(state["sent"], Exception):
            raise state["sent"]
        return state["sent"]

    monkeypatch.setattr(E, "_get", _get)
    monkeypatch.setattr(E, "_post", _post)
    return calls, state


async def test_it_sends_to_the_persons_own_connected_address(gmail):
    calls, _ = gmail
    problem = await E.send("owner@platform.example", "Inbox check", "completed",
                           "All quiet.")
    assert problem is None
    assert calls["get"] == [("/auth/status", "owner@platform.example")]
    path, who, body = calls["post"][0]
    assert path == "/gmail_send_email" and who == "owner@platform.example"
    assert body["to"] == "me@gmail.example", "only ever to their own address"
    assert body["subject"] == "Inbox check"
    assert "All quiet." in body["body"]


async def test_not_connected_says_so_and_sends_nothing(gmail):
    calls, state = gmail
    state["status"] = {"connected": False, "account": None}
    problem = await E.send("o@x.example", "Inbox check", "completed", "hi")
    assert problem and "Gmail" in problem and "connect" in problem.lower()
    assert calls["post"] == []


async def test_a_gmail_refusal_is_said_not_swallowed(gmail):
    _, state = gmail
    state["sent"] = {"error": "Gmail is not connected for this account."}
    problem = await E.send("o@x.example", "Inbox check", "completed", "hi")
    assert problem and "could not email" in problem.lower()


async def test_a_dead_gmail_service_never_raises(gmail):
    _, state = gmail
    state["status"] = RuntimeError("connection refused http://mcp-gmail:8000")
    problem = await E.send("o@x.example", "Inbox check", "completed", "hi")
    assert problem and "could not email" in problem.lower()
    assert "mcp-gmail" not in problem, "no internal address in a person's output"


async def test_the_gmail_check_for_a_create(gmail):
    _, state = gmail
    assert await E.gmail_problem("o@x.example") is None
    state["status"] = {"connected": False, "account": None}
    assert "connect" in (await E.gmail_problem("o@x.example")).lower()
    # Down is not "not connected": a create is never refused for an outage.
    state["status"] = RuntimeError("down")
    assert await E.gmail_problem("o@x.example") is None


# --- through _finalize_run -----------------------------------------------------

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


class _Sched:
    def __init__(self, **kw):
        self.id = "11111111-2222-3333-4444-555555555555"
        self.user_email = "me@example.com"
        self.name = "Weekly digest"
        self.agent_id = "agent.one"
        self.delivery_channel_id = None
        self.delivery_platform = "discord"
        self.run_once = False
        self.prompt = "Summarize this week's unread Gmail."
        self.last_result = ""
        self.last_run_status = None
        self.tool_mode = None
        if "email_me" in kw:
            self.email_me = kw["email_me"]


@pytest.fixture
def running(monkeypatch):
    state = {"writes": [], "history": [], "emails": []}
    monkeypatch.setattr(scheduler, "session", lambda: _FakeSession(state["writes"]))

    async def _record(values):
        state["history"].append(values)

    monkeypatch.setattr(scheduler, "_record_run", _record)
    monkeypatch.setattr(scheduler, "_deliver_result", AsyncMock())
    monkeypatch.setattr(scheduler.events_out, "emit", lambda *a, **k: None)

    async def _send(user_email, name, status, result):
        state["emails"].append((user_email, name, status, result))
        return state.get("problem")

    monkeypatch.setattr(scheduler.cron_email, "send", _send)
    return state


async def test_a_job_set_to_email_emails_its_answer(running, monkeypatch):
    async def _ran(sched):
        return "completed", "Three unread, none need a reply.", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched(email_me=True))
    assert running["emails"] == [("me@example.com", "Weekly digest", "completed",
                                  "Three unread, none need a reply.")]
    assert running["history"][0]["result"] == "Three unread, none need a reply."


async def test_a_job_not_set_to_email_sends_nothing(running, monkeypatch):
    async def _ran(sched):
        return "completed", "x", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())
    await scheduler._finalize_run(_Sched(email_me=False))
    assert running["emails"] == []


async def test_an_email_that_could_not_go_says_so_on_the_output(running,
                                                                monkeypatch):
    running["problem"] = "I could not email this: connect Gmail on Connections."

    async def _ran(sched):
        return "completed", "Three unread.", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched(email_me=True))
    stored = running["history"][0]["result"]
    assert stored.startswith("Three unread.")
    assert stored.endswith(running["problem"])


async def test_a_broken_email_step_never_costs_the_run(running, monkeypatch):
    async def _ran(sched):
        return "completed", "Three unread.", {}

    async def _boom(*a, **k):
        raise RuntimeError("bug in the email step")

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    monkeypatch.setattr(scheduler.cron_email, "send", _boom)
    await scheduler._finalize_run(_Sched(email_me=True))
    row = running["history"][0]
    assert row["status"] == "completed" and row["result"].startswith("Three unread.")


# --- the agent is told it does not send ---------------------------------------

def _wire_schedule(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([{"id": "agent.one", "name": "Ada",
                                                  "meta": {"toolIds": []}}], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_runner.agent_activity, "start_run",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(agent_runner.agent_graph, "graph_block",
                        AsyncMock(return_value=""))
    import user_skills
    monkeypatch.setattr(user_skills, "overlay_for", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner, "session_stamp_for", AsyncMock(return_value=None))
    import routes_agent_turn
    monkeypatch.setattr(routes_agent_turn, "tools_for_agent",
                        AsyncMock(return_value=[]))
    return seen


async def test_an_emailing_jobs_agent_is_told_the_platform_sends_it(monkeypatch):
    seen = _wire_schedule(monkeypatch)
    await agent_runner.run_agent(_Sched(email_me=True))
    brief = seen["messages"][0]["content"]
    assert E.BRIEF in brief
    assert seen["messages"][-1]["content"].startswith("Summarize"), \
        "the task stays the last thing the agent reads"


async def test_other_jobs_hear_nothing_about_email(monkeypatch):
    seen = _wire_schedule(monkeypatch)
    await agent_runner.run_agent(_Sched())
    assert E.BRIEF not in seen["messages"][0]["content"]


def test_the_brief_says_do_not_send_and_write_it_as_the_email():
    said = E.BRIEF.lower()
    assert "emailed" in said and "do not send" in said


# --- the switch on the row -----------------------------------------------------

def test_the_migration_adds_the_switch_off_for_every_existing_cron():
    sql = MIGRATION.read_text(encoding="utf-8")
    code = " ".join(" ".join(l for l in sql.splitlines()
                             if not l.strip().startswith("--")).split())
    assert ("ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS email_me "
            "BOOLEAN NOT NULL DEFAULT false") in code
    assert "UPDATE" not in code.upper()


def test_the_model_knows_the_switch():
    from models import Schedule
    col = Schedule.__table__.c.email_me
    assert col.nullable is False
    assert col.default.arg is False


def test_the_list_says_whether_a_job_emails():
    class Row:
        id = "x"; user_email = "e"; name = "n"; cron_expr = "0 9 * * *"
        tz = "UTC"; persona = ""; prompt = "p"; enabled = True
        last_run_at = None; last_run_status = None; last_result = None
        last_result_at = None; delivery_channel_id = None
        delivery_platform = "discord"; kind = "agent"; agent_id = None
        tool_mode = None
    assert R._serialize(Row())["email_me"] is False, "no column yet means off"
    Row.email_me = True
    assert R._serialize(Row())["email_me"] is True


# --- create and edit -----------------------------------------------------------

class _RouteSession:
    def __init__(self, seen):
        self.seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def add(self, row):
        self.seen.append(("add", row))

    async def execute(self, stmt, params=None):
        try:
            self.seen.append(("execute", dict(stmt.compile().params)))
        except Exception:                                   # noqa: BLE001
            self.seen.append(("execute", {}))

    async def commit(self):
        return None


@pytest.fixture
def routes(monkeypatch):
    seen = []
    state = {"gmail": None}

    class S:
        id = "11111111-2222-3333-4444-555555555555"
        user_email = "me@example.com"
        prompt = "Summarize my unread mail."

    async def _scoped(schedule_id, email):
        return S()

    async def _gmail_problem(email):
        return state["gmail"]

    monkeypatch.setattr(R, "_scoped_schedule", _scoped)
    monkeypatch.setattr(R, "session", lambda: _RouteSession(seen))
    monkeypatch.setattr(R, "_enforce_count_cap", AsyncMock())
    monkeypatch.setattr(R.cron_email, "gmail_problem", _gmail_problem)
    return seen, state


def _create(**kw):
    body = dict(name="Weekly digest", cron_expr="0 16 * * 5",
                prompt="Summarize this week's unread Gmail.", agent_id="agent.one")
    body.update(kw)
    return R.create_schedule(R.CreateScheduleIn(**body), x_cron_secret="",
                             x_user_email="me@example.com", x_user_admin="")


async def test_a_job_made_to_email_is_stored_that_way(routes):
    seen, _ = routes
    out = await _create(email_me=True)
    row = [r for k, r in seen if k == "add"][0]
    assert row.email_me is True
    assert out["email_me"] is True


async def test_a_job_is_not_emailed_unless_asked(routes):
    seen, _ = routes
    await _create()
    row = [r for k, r in seen if k == "add"][0]
    assert row.email_me is False


async def test_emailing_without_gmail_connected_is_refused_with_why(routes):
    seen, state = routes
    state["gmail"] = "To email you the answer, connect Gmail first."
    with pytest.raises(R.HTTPException) as e:
        await _create(email_me=True)
    assert e.value.status_code == 400
    assert "connect Gmail" in e.value.detail
    assert not [r for k, r in seen if k == "add"], "nothing was made"


async def test_an_edit_can_turn_email_on_and_off(routes):
    seen, _ = routes
    for on in (True, False):
        out = await R.update_schedule("11111111-2222-3333-4444-555555555555",
                                      R.UpdateScheduleIn(email_me=on),
                                      x_cron_secret="", x_user_email="me@example.com",
                                      x_user_admin="")
        assert out == {"status": "updated"}
        assert any(p.get("email_me") is on for k, p in seen if k == "execute")


async def test_turning_email_on_without_gmail_is_refused_before_any_write(routes):
    seen, state = routes
    state["gmail"] = "To email you the answer, connect Gmail first."
    with pytest.raises(R.HTTPException):
        await R.update_schedule("11111111-2222-3333-4444-555555555555",
                                R.UpdateScheduleIn(email_me=True, name="New name"),
                                x_cron_secret="", x_user_email="me@example.com",
                                x_user_admin="")
    assert not [k for k, _ in seen if k == "execute"]
