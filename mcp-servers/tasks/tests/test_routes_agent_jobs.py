"""Start, Cancel and Stop on a team job's plan card, and the Done badge.

The store and the worker are fakes: what is under test is that every button
is owner-checked, that Start wakes the worker and says so on the live feed,
and that the card handed back draws the job as it now is.
"""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

OWNER = "owner@example.com"
STRANGER = "stranger@example.com"
MIA = {"id": "agent-m", "name": "Mia"}
ADA = {"id": "agent-a", "name": "Ada"}
DEV = {"id": "agent-d", "name": "Dev"}


def _job(status="proposed", owner=OWNER):
    return {"id": "job-1", "user_email": owner, "chat_id": "chat-1",
            "lead_agent_id": "agent-m", "request": "weekly summary",
            "status": status, "result": None,
            "steps": [
                {"id": "s1", "position": 1, "agent_id": "agent-m",
                 "task": "find the <reports>", "status": "waiting"},
                {"id": "s2", "position": 2, "agent_id": "agent-a",
                 "task": "compare them", "status": "waiting"},
                {"id": "s3", "position": 3, "agent_id": "agent-d",
                 "task": "draft a page", "status": "waiting"}]}


class FakeStore:
    def __init__(self, job, start_ok=True, cancel_ok=True, unseen=0):
        self.job = job
        self.start_ok = start_ok
        self.cancel_ok = cancel_ok
        self.unseen = unseen
        self.calls = []

    async def for_owner(self, job_id, user_email):
        self.calls.append(("for_owner", job_id, user_email))
        if (self.job and job_id == self.job["id"]
                and user_email == self.job["user_email"]):
            return {**self.job, "steps": [dict(s) for s in self.job["steps"]]}
        return None

    async def start(self, job_id, user_email):
        self.calls.append(("start", job_id, user_email))
        if self.start_ok:
            self.job["status"] = "running"
        return self.start_ok

    async def cancel(self, job_id, user_email):
        self.calls.append(("cancel", job_id, user_email))
        if self.cancel_ok:
            self.job["status"] = "cancelled"
            for st in self.job["steps"]:
                if st["status"] in ("waiting", "running"):
                    st["status"] = "skipped"
        return self.cancel_ok

    async def unseen_count(self, user_email):
        self.calls.append(("unseen_count", user_email))
        return self.unseen if user_email == OWNER else 0

    async def mark_seen(self, user_email):
        self.calls.append(("mark_seen", user_email))
        if user_email == OWNER:
            self.unseen = 0


class FakeWorker:
    def __init__(self):
        self.woken = 0
        self.cancelled = []

    def wake(self):
        self.woken += 1

    def cancel(self, job_id):
        self.cancelled.append(job_id)


@pytest.fixture
def harness(monkeypatch):
    import routes_agent_jobs
    importlib.reload(routes_agent_jobs)

    store = FakeStore(_job())
    worker = FakeWorker()
    events = []

    async def agents_for(email):
        return [MIA, ADA, DEV]

    def publish(event, **kw):
        events.append((event, kw))

    monkeypatch.setattr(routes_agent_jobs, "job_store", store)
    monkeypatch.setattr(routes_agent_jobs, "agent_job_worker", worker)
    monkeypatch.setattr(routes_agent_jobs, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_jobs.agent_events, "publish", publish)

    app = FastAPI()
    app.include_router(routes_agent_jobs.router)
    client = TestClient(app)
    return client, store, worker, events


def _hdr(email=OWNER):
    return {"X-User-Email": email}


def test_start_runs_the_job_wakes_the_worker_and_says_so(harness):
    client, store, worker, events = harness
    r = client.post("/tasks/agents/jobs/job-1/start", headers=_hdr())
    assert r.status_code == 200
    assert ("start", "job-1", OWNER) in store.calls
    assert worker.woken == 1
    started = [kw for e, kw in events if e == "job_started"]
    assert started == [{"agent_id": "agent-m", "user_email": OWNER,
                        "job_id": "job-1", "of": 3,
                        "participants": ["agent-m", "agent-a", "agent-d"]}]
    # The card comes back drawn as the job now is: running, with Stop.
    assert 'id="job-job-1"' in r.text
    assert "Running: step 1 of 3" in r.text
    assert ">Stop<" in r.text and ">Start<" not in r.text
    # Names from the roster, and the task text escaped.
    assert "Mia: find the &lt;reports&gt;" in r.text


def test_a_refused_start_says_so_and_runs_nothing(harness):
    client, store, worker, events = harness
    store.start_ok = False
    r = client.post("/tasks/agents/jobs/job-1/start", headers=_hdr())
    assert r.status_code == 200
    assert "This plan can no longer be started." in r.text
    assert worker.woken == 0
    assert not [e for e, _ in events if e == "job_started"]
    # Still a whole card, so the swap replaces it rather than nesting it.
    assert r.text.count('id="job-job-1"') == 1


def test_cancel_stops_the_job_and_its_running_step(harness):
    client, store, worker, events = harness
    store.job["status"] = "running"
    r = client.post("/tasks/agents/jobs/job-1/cancel", headers=_hdr())
    assert r.status_code == 200
    assert ("cancel", "job-1", OWNER) in store.calls
    assert worker.cancelled == ["job-1"]
    assert "Cancelled" in r.text
    assert ">Stop<" not in r.text and ">Start<" not in r.text
    finished = [kw for e, kw in events if e == "job_finished"]
    assert finished == [{"agent_id": "agent-m", "user_email": OWNER,
                         "job_id": "job-1", "status": "cancelled"}]


def test_cancel_of_a_job_already_over_changes_nothing(harness):
    client, store, worker, events = harness
    store.job["status"] = "done"
    store.cancel_ok = False
    r = client.post("/tasks/agents/jobs/job-1/cancel", headers=_hdr())
    assert r.status_code == 200
    assert "Done" in r.text
    assert not [e for e, _ in events if e == "job_finished"]


@pytest.mark.parametrize("action", ["start", "cancel"])
def test_another_persons_job_is_not_found(harness, action):
    client, store, worker, events = harness
    r = client.post(f"/tasks/agents/jobs/job-1/{action}",
                    headers=_hdr(STRANGER))
    assert r.status_code == 404
    assert "weekly" not in r.text and "reports" not in r.text
    # Nothing was attempted on the owner's job.
    assert not [c for c in store.calls if c[0] in ("start", "cancel")]
    assert worker.woken == 0 and worker.cancelled == []
    assert events == []


def test_an_unknown_job_is_not_found(harness):
    client, store, worker, events = harness
    r = client.post("/tasks/agents/jobs/nope/start", headers=_hdr())
    assert r.status_code == 404


def test_the_badge_counts_jobs_finished_while_away(harness):
    client, store, worker, events = harness
    store.unseen = 2
    r = client.get("/tasks/agents/jobs/badge", headers=_hdr())
    assert r.status_code == 200 and r.json() == {"unseen": 2}
    assert client.get("/tasks/agents/jobs/badge",
                      headers=_hdr(STRANGER)).json() == {"unseen": 0}
    r = client.post("/tasks/agents/jobs/seen", headers=_hdr())
    assert r.status_code == 200
    assert ("mark_seen", OWNER) in store.calls
    assert client.get("/tasks/agents/jobs/badge",
                      headers=_hdr()).json() == {"unseen": 0}


def test_a_badge_that_cannot_be_read_shows_nothing(harness, monkeypatch):
    client, store, worker, events = harness

    async def broken(user_email):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "unseen_count", broken)
    r = client.get("/tasks/agents/jobs/badge", headers=_hdr())
    assert r.status_code == 200 and r.json() == {"unseen": 0}


def test_no_signed_in_person_is_refused(harness):
    client, store, worker, events = harness
    assert client.post("/tasks/agents/jobs/job-1/start").status_code == 401


def test_the_service_serves_these_routes(monkeypatch):
    """Included in main.py, or every button on every card is a 404."""
    import os
    if not os.environ.get("AIUI_FERNET_KEY"):
        from cryptography.fernet import Fernet
        monkeypatch.setenv("AIUI_FERNET_KEY", Fernet.generate_key().decode())
    from main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    for path in ("/tasks/agents/jobs/{job_id}/start",
                 "/tasks/agents/jobs/{job_id}/cancel",
                 "/tasks/agents/jobs/badge", "/tasks/agents/jobs/seen"):
        assert path in paths
