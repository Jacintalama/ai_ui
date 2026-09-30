"""Every event the floor draws is a row that was really written."""
import pytest

import agent_activity


@pytest.fixture(autouse=True)
def _no_agent_step_recording():
    """Overrides conftest's mute: these tests exercise record_step itself."""
    yield


@pytest.fixture
def sent(monkeypatch):
    got = []
    monkeypatch.setattr(agent_activity.agent_events, "publish",
                        lambda event, **kw: got.append((event, kw)))
    return got


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, row=None):
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **kw):
        return _Result(self.row)

    async def commit(self):
        pass


class _Boom:
    async def __aenter__(self):
        raise RuntimeError("the database is not there")

    async def __aexit__(self, *a):
        return False


async def test_start_run_announces_the_run_it_wrote(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session())
    run_id = await agent_activity.start_run("agent-a", "me@example.com",
                                            agent_activity.SOURCE_CHANNEL)
    assert run_id
    assert sent == [("run_started", {"agent_id": "agent-a",
                                     "user_email": "me@example.com"})]


async def test_a_run_that_was_not_written_is_not_announced(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    assert await agent_activity.start_run(
        "agent-a", "me@example.com", agent_activity.SOURCE_CHANNEL) is None
    assert sent == []


async def test_finish_run_announces_whose_run_ended_and_how(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session",
                        lambda: _Session(row=("agent-a", "me@example.com")))
    await agent_activity.finish_run("run-1", "ok")
    assert sent == [("run_finished", {"agent_id": "agent-a",
                                      "user_email": "me@example.com",
                                      "status": "ok"})]


async def test_finishing_an_unknown_run_announces_nothing(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session(row=None))
    await agent_activity.finish_run("run-nobody-wrote", "ok")
    assert sent == []


async def test_a_step_announces_the_tool_that_finished(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session())
    await agent_activity.record_step("run-1", "agent-a", "me@example.com",
                                     "search_drive", "ok")
    assert sent == [("tool_finished", {"agent_id": "agent-a",
                                       "user_email": "me@example.com",
                                       "tool": "search_drive",
                                       "status": "ok"})]


async def test_a_step_with_a_colleague_is_also_a_handoff(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session())
    await agent_activity.record_step("run-1", "agent-a", "me@example.com",
                                     "ask_colleague", "ok",
                                     target_agent_id="agent-b")
    assert [e for e, _ in sent] == ["tool_finished", "handoff"]
    assert sent[1][1]["target_agent_id"] == "agent-b"


async def test_a_step_that_was_not_written_is_not_announced(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    await agent_activity.record_step("run-1", "agent-a", "me@example.com",
                                     "search_drive", "ok")
    assert sent == []
