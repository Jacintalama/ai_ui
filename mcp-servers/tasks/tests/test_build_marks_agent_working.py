"""An agent that starts an app build is working until the build ends.

Rex asked the builder for a landing page; his chat turn ended in seconds,
and the office drew him as Ready while the build ran for minutes
(screenshot, 2026-10-17: "it should be in progress working"). The build
route now opens a run that IS the build, and the execution pipeline closes
it when the item finishes.

No database: the builder, the run bookkeeping and the app URL are all
replaced by records of what they were asked.
"""
import importlib
import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import agent_activity

SECRET = "build-marks-secret"
OWNER = "build-marks@example.com"


@pytest.fixture
def mod(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    import routes_code
    importlib.reload(routes_code)
    monkeypatch.setattr(routes_code, "_apps_root_override", tmp_path, raising=False)
    return routes_code


@pytest.fixture
def client(mod):
    app = FastAPI()
    app.include_router(mod.router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def seams(mod, monkeypatch):
    got = {"runs": []}

    async def spawn(user_email, seed, description, design_skill=None):
        return "27e46f49-c64f-4a17-87ce-975c35045aa3", "icecream-landing-page-530d"

    async def url(slug):
        return "https://ai-ui.example/apps/" + slug

    async def start_run(agent_id, user_email, source, parent_run_id=None, task_id=None):
        got["runs"].append({"agent_id": agent_id, "user_email": user_email,
                            "source": source, "task_id": task_id})
        return "run-1"

    async def design(user_email, agent_id):
        return None

    monkeypatch.setattr(mod, "_spawn_build", spawn)
    monkeypatch.setattr(mod, "app_url", url)
    monkeypatch.setattr(mod, "_design_for", design)
    monkeypatch.setattr(agent_activity, "start_run", start_run)
    return got


async def _create(client, **body):
    return await client.post("/code/create", json=body,
                             headers={"X-Internal-Secret": SECRET})


async def test_a_build_an_agent_asked_for_opens_a_run_that_is_the_build(client, seams):
    r = await _create(client, user_email=OWNER, description="a landing page for icecream",
                      agent_id="agent-rex-7")
    assert r.status_code == 200, r.text
    assert seams["runs"] == [{"agent_id": "agent-rex-7", "user_email": OWNER,
                              "source": agent_activity.SOURCE_BUILD,
                              "task_id": "27e46f49-c64f-4a17-87ce-975c35045aa3"}]


async def test_a_build_nobody_asked_for_opens_no_run(client, seams):
    """The person used the builder themselves: no agent is working."""
    r = await _create(client, user_email=OWNER, description="a landing page for icecream")
    assert r.status_code == 200, r.text
    assert seams["runs"] == []


async def test_bookkeeping_that_fails_does_not_fail_the_build(client, seams, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("no database")
    monkeypatch.setattr(agent_activity, "start_run", boom)
    r = await _create(client, user_email=OWNER, description="a page", agent_id="agent-rex-7")
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "icecream-landing-page-530d"


def test_a_build_run_reads_as_working_for_longer_than_a_chat_turn():
    """A chat run unfinished after 23 minutes is a failure; a build takes
    that long on purpose."""
    assert agent_activity._stale_after(agent_activity.SOURCE_BUILD) > agent_activity.STALE_AFTER_CHANNEL
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    row = {"source": agent_activity.SOURCE_BUILD, "status": None, "finished_at": None,
           "started_at": now - timedelta(minutes=30)}
    assert agent_activity._shape(row, now)["state"] == "working"


def test_the_builds_outcome_is_said_in_the_runs_words():
    assert agent_activity.BUILD_OUTCOME_STATUS == {
        "completed": "completed", "needs_steps": "completed",
        "needs_input": "waiting", "failed": "failed"}


async def test_the_pipeline_closes_the_run_and_never_raises(monkeypatch):
    import routes_execution
    closed = []

    async def finish(task_id, status):
        closed.append((task_id, status))
        return 1
    monkeypatch.setattr(agent_activity, "finish_task_runs", finish)
    await routes_execution._finish_agent_runs("task-9", "needs_input")
    assert closed == [("task-9", "waiting")]

    async def boom(task_id, status):
        raise RuntimeError("no database")
    monkeypatch.setattr(agent_activity, "finish_task_runs", boom)
    await routes_execution._finish_agent_runs("task-9", "completed")
