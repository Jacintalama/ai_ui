"""Every tool call leaves a row, and a failed row never costs a turn."""
import agent_runner


def _started(monkeypatch):
    calls = []

    async def start_step(run_id, agent_id, user_email, tool,
                         target_agent_id=None):
        calls.append({"run": run_id, "agent": agent_id, "tool": tool,
                      "target": target_agent_id})
        return "step-%d" % len(calls)

    async def finish_step(step_id, status):
        calls.append({"finished": step_id, "status": status})

    monkeypatch.setattr(agent_runner.agent_activity, "start_step", start_step)
    monkeypatch.setattr(agent_runner.agent_activity, "finish_step", finish_step)
    return calls


async def test_a_tool_call_is_recorded(monkeypatch):
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}},
        "ok")
    assert calls[0]["tool"] == "search_drive"
    assert calls[0]["target"] is None
    assert calls[1]["status"] == "ok"


async def test_a_handoff_records_who_was_asked(monkeypatch):
    calls = _started(monkeypatch)
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
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "send_email", "arguments": "{}"}},
        "refused")
    assert calls[1]["status"] == "refused"


async def test_recording_that_fails_does_not_raise(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("the database is not there")

    monkeypatch.setattr(agent_runner.agent_activity, "start_step", boom)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}}, "ok")


async def test_a_call_with_no_name_records_nothing(monkeypatch):
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com", {"function": {}}, "ok")
    assert calls == []
