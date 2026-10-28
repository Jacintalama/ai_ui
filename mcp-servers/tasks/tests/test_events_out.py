"""Events out (2026-10-28): the platform tells a URL what happened.

What has to hold: a hook gets only the events it asked for, signed with
its secret; a post is retried on a server error and not on a client one;
nothing on the way out can reach the thing that happened; the URL has to
be public; and every finish point emits.
"""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import events_out as ev
import routes_events as re_
from auth import CurrentUser, current_user

OWNER = "owner@example.com"


def _hook(**over):
    base = {"id": "h1", "url": "https://hooks.example.com/io", "secret": "ehs_secret",
            "events": ["*"], "enabled": True, "label": "n8n"}
    base.update(over)
    return base


# --- shaping and signing ------------------------------------------------------

def test_events_are_validated_and_star_means_all():
    assert ev.clean_events(["build.finished", "nope", "build.finished"]) == ["build.finished"]
    assert ev.clean_events([]) == ["*"] and ev.clean_events(None) == ["*"]
    assert ev.clean_events(["schedule.finished", "*"]) == ["*"]
    assert ev.wants(_hook(events=["*"]), "minutes.taken")
    assert ev.wants(_hook(events=["build.finished"]), "build.finished")
    assert not ev.wants(_hook(events=["build.finished"]), "minutes.taken")


def test_the_body_is_signed_with_the_hooks_secret():
    body = b'{"event": "build.finished"}'
    sig = ev.sign("ehs_secret", body)
    assert sig.startswith("sha256=") and ev.verify("ehs_secret", body, sig)
    assert not ev.verify("ehs_other", body, sig)
    assert not ev.verify("ehs_secret", body, "")


def test_the_envelope_carries_the_event_a_time_an_id_and_clipped_data():
    env = ev.envelope("automation.finished", {"answer": "x" * 10_000, "list": list(range(100))})
    assert env["event"] == "automation.finished" and env["at"] and len(env["id"]) == 32
    assert len(env["data"]["answer"]) == ev.MAX_TEXT and len(env["data"]["list"]) == 50


def test_a_hook_row_shows_only_a_prefix_of_the_secret():
    class H:
        id = "h1"; url = "https://x"; label = ""; events = ["*"]; enabled = True
        secret = "ehs_abcdefghij"; created_at = None; last_sent_at = None
        last_result = ""; fail_count = 0
    row = ev.row_of(H())
    assert row["secret_prefix"] == "ehs_abcd" and "secret" not in row


# --- sending --------------------------------------------------------------------

@pytest.fixture
def wire(monkeypatch):
    seen = {"posts": [], "notes": [], "hooks": [_hook()]}

    async def post(url, body, signature, event):
        seen["posts"].append((url, json.loads(body), signature, event))
        return True, "ok"

    async def note(hook_id, ok, result):
        seen["notes"].append((hook_id, ok, result))

    async def hooks(email, enabled_only=False):
        return [h for h in seen["hooks"] if h.get("enabled", True) or not enabled_only] if email == OWNER else []

    monkeypatch.setattr(ev, "_post", post)
    monkeypatch.setattr(ev, "_note", note)
    monkeypatch.setattr(ev, "_hooks", hooks)
    monkeypatch.setattr(ev, "_sleep", AsyncMock())
    return seen


async def test_a_post_carries_the_signed_envelope_and_is_noted(wire):
    assert await ev.deliver(_hook(), "build.finished", {"slug": "shop"}) is True
    url, body, sig, event = wire["posts"][0]
    assert url == "https://hooks.example.com/io" and event == "build.finished"
    assert body["event"] == "build.finished" and body["data"] == {"slug": "shop"}
    assert ev.verify("ehs_secret", json.dumps(body, ensure_ascii=False, default=str).encode(), sig)
    assert wire["notes"] == [("h1", True, "ok")]


async def test_a_server_error_is_retried_and_a_client_error_is_not(wire, monkeypatch):
    answers = iter([(False, "http 503"), (True, "ok")])
    monkeypatch.setattr(ev, "_post", AsyncMock(side_effect=lambda *a: next(answers)))
    assert await ev.deliver(_hook(), "build.finished", {}) is True
    assert ev._post.await_count == 2
    monkeypatch.setattr(ev, "_post", AsyncMock(return_value=(False, "http 404")))
    assert await ev.deliver(_hook(), "build.finished", {}) is False
    assert ev._post.await_count == 1
    assert wire["notes"][-1] == ("h1", False, "http 404")


async def test_a_connection_failure_is_tried_three_times_then_noted(wire, monkeypatch):
    import httpx
    monkeypatch.setattr(ev, "_post", AsyncMock(side_effect=httpx.ConnectError("no route")))
    assert await ev.deliver(_hook(), "build.finished", {}) is False
    assert ev._post.await_count == ev.TRIES
    assert wire["notes"][-1] == ("h1", False, "ConnectError")


async def test_send_posts_to_the_hooks_that_want_the_event(wire):
    wire["hooks"] = [_hook(id="h1", events=["build.finished"]),
                     _hook(id="h2", events=["minutes.taken"]),
                     _hook(id="h3", events=["*"], enabled=False)]
    assert await ev.send(OWNER, "build.finished", {"slug": "shop"}) == 1
    assert [p[0] for p in wire["posts"]] == ["https://hooks.example.com/io"]
    assert await ev.send("stranger@example.com", "build.finished", {}) == 0


async def test_emit_returns_at_once_and_ignores_unknown_events(wire, monkeypatch):
    spawned = []
    monkeypatch.setattr(ev, "_spawn", lambda coro: spawned.append(coro) or type("T", (), {
        "add_done_callback": lambda self, cb: None})())
    ev.emit(OWNER, "build.finished", {"slug": "shop"})
    ev.emit(OWNER, "not.an.event", {})
    ev.emit("", "build.finished", {})
    assert len(spawned) == 1
    await spawned[0]
    assert wire["posts"][0][3] == "build.finished"


async def test_a_hooks_read_that_fails_sends_nothing_and_raises_nothing(wire, monkeypatch):
    monkeypatch.setattr(ev, "_hooks", AsyncMock(side_effect=RuntimeError("db down")))
    assert await ev.send(OWNER, "build.finished", {}) == 0


# --- the routes -------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    rows = []

    async def hooks(email, enabled_only=False):
        return [dict(r) for r in rows if r["user_email"] == email]

    async def create(email, fields):
        if len([r for r in rows if r["user_email"] == email]) >= ev.MAX_HOOKS:
            raise ev.TooMany()
        rows.append(dict(fields, id="h%d" % (len(rows) + 1), user_email=email, secret=ev.make_secret(),
                         secret_prefix="", created_at=None, last_sent_at=None, last_result="", fail_count=0))
        return {k: v for k, v in rows[-1].items() if k != "user_email"}

    async def update(email, hid, changes):
        r = next((r for r in rows if r["id"] == hid and r["user_email"] == email), None)
        if not r:
            return None
        r.update(changes)
        return {k: v for k, v in r.items() if k not in ("user_email", "secret")}

    async def delete(email, hid):
        before = len(rows)
        rows[:] = [r for r in rows if not (r["id"] == hid and r["user_email"] == email)]
        return len(rows) < before

    monkeypatch.setattr(ev, "_hooks", hooks)
    monkeypatch.setattr(ev, "_create", create)
    monkeypatch.setattr(ev, "_update", update)
    monkeypatch.setattr(ev, "_delete", delete)
    monkeypatch.setattr(ev, "_post", AsyncMock(return_value=(True, "ok")))
    monkeypatch.setattr(ev, "_note", AsyncMock())
    import routes_automation
    monkeypatch.setattr(routes_automation, "_resolve_seam", lambda host: ["93.184.216.34"])
    app = FastAPI()
    app.include_router(re_.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    c = TestClient(app)
    c.rows = rows
    return c


def test_a_hook_is_made_with_its_secret_once_then_listed_changed_tested_and_deleted(client):
    r = client.post("/api/tasks/events/hooks", json={"url": "https://hooks.example.com/io",
                                                     "events": ["build.finished", "nope"], "label": "n8n"})
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["secret"].startswith("ehs_") and made["events"] == ["build.finished"]
    listed = client.get("/api/tasks/events/hooks").json()
    assert listed["hooks"][0]["id"] == "h1" and "secret" not in listed["hooks"][0]
    assert listed["events"] == list(ev.EVENTS)
    r = client.patch("/api/tasks/events/hooks/h1", json={"enabled": False, "events": ["*"]})
    assert r.json()["enabled"] is False and r.json()["events"] == ["*"]
    r = client.post("/api/tasks/events/hooks/h1/test")
    assert r.json()["ok"] is True and ev._post.await_args.args[3] == "automation.finished"
    assert client.delete("/api/tasks/events/hooks/h1").json() == {"deleted": True}
    assert client.patch("/api/tasks/events/hooks/h1", json={"enabled": True}).status_code == 404


@pytest.mark.parametrize("url", ["http://localhost/x", "ftp://x.example.com", "http://tasks.internal/x"])
def test_a_hook_must_be_a_public_web_address(client, url):
    r = client.post("/api/tasks/events/hooks", json={"url": url})
    assert r.status_code == 422


def test_the_hook_limit_is_a_sentence(client, monkeypatch):
    monkeypatch.setattr(ev, "_create", AsyncMock(side_effect=ev.TooMany()))
    r = client.post("/api/tasks/events/hooks", json={"url": "https://hooks.example.com/io"})
    assert r.status_code == 409 and "Delete one" in r.json()["detail"]


# --- the finish points ------------------------------------------------------------

@pytest.fixture
def emitted(monkeypatch):
    seen = []
    monkeypatch.setattr(ev, "emit", lambda email, event, data: seen.append((email, event, data)))
    return seen


async def test_an_automation_run_emits(emitted, monkeypatch):
    import automation_runner, automations
    monkeypatch.setattr(automation_runner, "_run_turn_seam", AsyncMock(return_value={"answer": "Done.", "notes": []}))
    monkeypatch.setattr(automation_runner, "_to_chat_seam", AsyncMock(return_value="chat"))
    monkeypatch.setattr(automations, "_record_run", AsyncMock())
    await automation_runner.fire({"id": "a1", "user_email": OWNER, "agent_id": "agent-ada-1", "name": "Lead",
                                  "instructions": "Reply.", "deliver_to": "chat"}, {"name": "Bo"}, "Ada")
    email, event, data = emitted[0]
    assert (email, event) == (OWNER, "automation.finished")
    assert data["status"] == "done" and data["answer"] == "Done." and data["automation_id"] == "a1"


async def test_a_held_question_and_its_answer_emit(emitted, monkeypatch):
    import agent_approvals as ap
    import routes_approvals as ra
    monkeypatch.setattr(ap, "_create", AsyncMock(return_value={"id": "ap1"}))
    call = {"id": "c1", "type": "function", "function": {"name": "send_email", "arguments": "{}"}}
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", {"calls": [call], "conversation": []},
                           ap.ORIGIN_AUTOMATION, "a1")
    assert emitted[-1][1] == "approval.requested"
    assert emitted[-1][2]["approval_id"] == "ap1" and emitted[-1][2]["tools"] == ["send_email"]
    monkeypatch.setattr(ap, "_get", AsyncMock(return_value={
        "id": "ap1", "status": "pending", "agent_id": "agent-ada-1", "agent_name": "Ada",
        "origin": "automation", "origin_ref": "a1", "calls": [call], "conversation": []}))
    monkeypatch.setattr(ap, "_settle", AsyncMock(return_value=True))
    monkeypatch.setattr(ra, "_resume_seam", AsyncMock(return_value={"answer": "Sent.", "notes": []}))
    monkeypatch.setattr(ra, "_deliver_automation_seam", AsyncMock(return_value="chat"))
    await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    assert emitted[-1][1] == "approval.decided"
    assert emitted[-1][2]["approved"] is True and emitted[-1][2]["answer"] == "Sent."


async def test_a_scheduled_run_emits(emitted, monkeypatch):
    import scheduler

    class _S:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, *a, **k): return None
        async def commit(self): return None

    monkeypatch.setattr(scheduler, "session", lambda: _S())
    monkeypatch.setattr(scheduler, "_run_scheduled_task", AsyncMock(return_value=("completed", "Two due.", {})))

    class Sched:
        id = "s1"; name = "Morning inbox"; agent_id = "agent-ada-1"; user_email = OWNER
        delivery_channel_id = None
    await scheduler._finalize_run(Sched())
    email, event, data = emitted[0]
    assert (email, event) == (OWNER, "schedule.finished")
    assert data["status"] == "completed" and data["result"] == "Two due." and data["name"] == "Morning inbox"


def test_the_build_finish_point_names_the_event():
    import inspect
    import routes_execution
    src = inspect.getsource(routes_execution._run_execution)
    assert 'events_out.emit(assignee_email, "build.finished"' in src
    assert '"outcome": "failed"' in src, "a run that blew up is not reported"


def test_minutes_emit_is_wired():
    import inspect
    import routes_agent_chat
    src = inspect.getsource(routes_agent_chat._minutes_events)
    assert 'events_out.emit(email, "minutes.taken"' in src
