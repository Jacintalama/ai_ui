"""Recording what an agent did, without ever costing it its turn.

Only the in-memory half runs here. The SQL half needs a real Postgres and is
verified in the container: this repo's destructive DB tests once wiped nine
production projects, so they are not run locally.
"""
import agent_activity


class _Boom:
    """A session that fails the way a database that is down fails."""
    async def __aenter__(self):
        raise RuntimeError("the database is not there")

    async def __aexit__(self, *a):
        return False


async def test_a_step_with_no_run_records_nothing():
    """start_run returns None when its own write failed. A step belonging to
    a run that was never recorded has nothing to hang off."""
    assert await agent_activity.start_step(
        None, "agent-a", "me@example.com", "search_drive") is None


async def test_a_step_with_no_tool_records_nothing():
    assert await agent_activity.start_step(
        "run-1", "agent-a", "me@example.com", "") is None


async def test_a_failing_insert_does_not_raise(monkeypatch):
    """Review Focus 5 support, and the rule the whole module follows: the
    run matters, the bookkeeping does not."""
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    assert await agent_activity.start_step(
        "run-1", "agent-a", "me@example.com", "search_drive") is None


async def test_finishing_a_step_that_was_never_recorded_is_safe():
    await agent_activity.finish_step(None, "ok")


async def test_a_failing_finish_does_not_raise(monkeypatch):
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    await agent_activity.finish_step("step-1", "ok")


async def test_there_is_a_colleague_source():
    """So the office can say 'Iris is helping Nora' as a fact rather than an
    animation."""
    assert agent_activity.SOURCE_COLLEAGUE == "colleague"
