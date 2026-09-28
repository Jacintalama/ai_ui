"""Every tool call leaves a row, and a failed row never costs a turn."""
import agent_runner


def _recorded(monkeypatch):
    calls = []

    async def record_step(run_id, agent_id, user_email, tool, status,
                          target_agent_id=None):
        calls.append({"run": run_id, "agent": agent_id, "tool": tool,
                      "status": status, "target": target_agent_id})

    monkeypatch.setattr(agent_runner.agent_activity, "record_step",
                        record_step)
    return calls


async def test_a_tool_call_is_recorded(monkeypatch):
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}},
        "ok")
    assert calls[0]["tool"] == "search_drive"
    assert calls[0]["target"] is None
    assert calls[0]["status"] == "ok"


async def test_a_handoff_records_who_was_asked(monkeypatch):
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "ask_colleague",
                      "arguments": '{"agent": "Iris", "question": "hi"}'}},
        "ok")
    assert calls[0]["tool"] == "ask_colleague"
    assert calls[0]["target"] == "Iris"


async def test_a_refused_call_is_still_recorded(monkeypatch):
    """Review Focus 5. A refusal is a fact worth having, and a row left
    saying running for ever would read as a tool that hung."""
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "send_email", "arguments": "{}"}},
        "refused")
    assert calls[0]["status"] == "refused"


async def test_recording_that_fails_does_not_raise(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("the database is not there")

    monkeypatch.setattr(agent_runner.agent_activity, "record_step", boom)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}}, "ok")


async def test_a_call_with_no_name_records_nothing(monkeypatch):
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com", {"function": {}}, "ok")
    assert calls == []
