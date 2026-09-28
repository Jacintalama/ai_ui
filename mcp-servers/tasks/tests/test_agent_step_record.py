"""Recording what an agent did, without ever costing it its turn.

Only the in-memory half runs here. The SQL half needs a real Postgres and is
verified in the container: this repo's destructive DB tests once wiped nine
production projects, so they are not run locally.
"""
import pytest

import agent_activity


@pytest.fixture(autouse=True)
def _no_agent_step_recording():
    """Override conftest's global mute of record_step for this file only.

    That fixture exists so callers of record_step don't pay a DNS timeout
    for bookkeeping they aren't testing. This file IS testing record_step,
    so muting it here would make every test below pass by calling a no-op
    rather than the guard and try/except it means to exercise. Same fixture
    name, defined closer to the tests, wins over the conftest one.
    """
    yield


class _Boom:
    """A session that fails the way a database that is down fails."""
    async def __aenter__(self):
        raise RuntimeError("the database is not there")

    async def __aexit__(self, *a):
        return False


async def test_a_step_with_no_run_records_nothing(monkeypatch):
    """start_run returns None when its own write failed. A step belonging to
    a run that was never recorded has nothing to hang off, and the guard
    must trip before session() is ever opened -- not merely swallow a
    failure from it, which would look identical from the caller's side."""
    opened = []
    monkeypatch.setattr(agent_activity, "session", lambda: opened.append(1))
    await agent_activity.record_step(
        None, "agent-a", "me@example.com", "search_drive", "ok")
    assert opened == []


async def test_a_step_with_no_tool_records_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(agent_activity, "session", lambda: opened.append(1))
    await agent_activity.record_step(
        "run-1", "agent-a", "me@example.com", "", "ok")
    assert opened == []


async def test_a_failing_insert_does_not_raise(monkeypatch):
    """Review Focus 5 support, and the rule the whole module follows: the
    run matters, the bookkeeping does not."""
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    await agent_activity.record_step(
        "run-1", "agent-a", "me@example.com", "search_drive", "ok")


async def test_there_is_a_colleague_source():
    """So the office can say 'Iris is helping Nora' as a fact rather than an
    animation."""
    assert agent_activity.SOURCE_COLLEAGUE == "colleague"
