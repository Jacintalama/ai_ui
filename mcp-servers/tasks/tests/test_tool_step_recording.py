"""Every tool call leaves a row, and a failed row never costs a turn.

The status comes from a ToolOutcome the producing code filled in, never from
the sentence the model reads. Reading it off the sentence is what filed every
handoff refusal as `ok` and left `failed` unwritten by any path, in the one
table the design commissions to say how often a handoff ended ok.
"""
import agent_activity
import agent_runner
from agent_tools import ToolOutcome


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
        ToolOutcome())
    assert calls[0]["tool"] == "search_drive"
    assert calls[0]["target"] is None
    assert calls[0]["status"] == agent_activity.STEP_OK


async def test_a_handoff_records_the_resolved_agent_id(monkeypatch):
    """The id run_handoff resolved, not the name the model typed. The column
    is meant to join against agent_run.agent_id, and this table stores no
    prose, so a model that puts a sentence in `agent` must not land that
    sentence here."""
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "ask_colleague",
                      "arguments": '{"agent": "please ask Iris for the spec",'
                                   ' "question": "hi"}'}},
        ToolOutcome(target_agent_id="agent-iris"))
    assert calls[0]["tool"] == "ask_colleague"
    assert calls[0]["target"] == "agent-iris"


async def test_a_handoff_that_resolved_nobody_records_no_target(monkeypatch):
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "ask_colleague",
                      "arguments": '{"agent": "Nobody", "question": "hi"}'}},
        ToolOutcome(status=agent_activity.STEP_REFUSED))
    assert calls[0]["target"] is None
    assert calls[0]["status"] == agent_activity.STEP_REFUSED


async def test_a_refused_call_is_still_recorded(monkeypatch):
    """Review Focus 5. A refusal is a fact worth having, and a row left
    saying running for ever would read as a tool that hung."""
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "send_email", "arguments": "{}"}},
        ToolOutcome(status=agent_activity.STEP_REFUSED))
    assert calls[0]["status"] == agent_activity.STEP_REFUSED


async def test_a_failed_call_is_recorded_as_failed(monkeypatch):
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}},
        ToolOutcome(status=agent_activity.STEP_FAILED))
    assert calls[0]["status"] == agent_activity.STEP_FAILED


async def test_recording_that_fails_does_not_raise(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("the database is not there")

    monkeypatch.setattr(agent_runner.agent_activity, "record_step", boom)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}},
        ToolOutcome())


async def test_an_outcome_of_the_wrong_shape_does_not_raise(monkeypatch):
    """Recording fails open, which includes failing open on a bug in the
    caller: a turn must not die because something handed this the wrong
    object."""
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}}, None)
    assert calls[0]["status"] == agent_activity.STEP_OK


async def test_a_call_with_no_name_records_nothing(monkeypatch):
    calls = _recorded(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com", {"function": {}},
        ToolOutcome())
    assert calls == []


# --- The loop wires it, which is the half a unit test of _record_step misses -

def _reply(content=None, calls=None):
    msg = {"content": content or "", "tool_calls": calls or None}
    return {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}


def _tool_call(name):
    return {"id": "call_1", "type": "function",
            "function": {"name": name, "arguments": "{}"}}


async def _two_rounds(monkeypatch, name):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call(name)])
        return _reply(content="Here is what I have.")

    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)


async def _must_not_run(*a, **k):
    raise AssertionError("read_only must not execute a write tool")


async def test_the_loop_records_a_write_refused_in_read_only_as_refused(
        monkeypatch):
    """The loop writes this refusal itself rather than getting it from
    execute_tool_call, so it has to classify it itself too."""
    calls = _recorded(monkeypatch)
    await _two_rounds(monkeypatch, "send_email")
    monkeypatch.setattr(agent_runner, "execute_tool_call",
                        _must_not_run)

    await agent_runner._chat(
        token="t", model="agent-nora",
        messages=[{"role": "user", "content": "q"}],
        tool_ids=["gmail"], user_email="me@example.com",
        tool_mode="read_only",
        usage=agent_runner.agent_escalation.TurnUsage(run_id="run-1"))

    assert [c["status"] for c in calls] == [agent_activity.STEP_REFUSED]


async def test_the_loop_records_what_the_tool_reported(monkeypatch):
    """A failing tool records `failed`, which no path wrote before: the loop
    hands execute_tool_call an outcome and records what comes back on it."""
    calls = _recorded(monkeypatch)
    await _two_rounds(monkeypatch, "search_drive")

    async def failing(call, user_email, tool_ids, agent_id, outcome=None):
        return outcome.failed("The tool search_drive could not be run.")

    monkeypatch.setattr(agent_runner, "execute_tool_call", failing)

    await agent_runner._chat(
        token="t", model="agent-nora",
        messages=[{"role": "user", "content": "q"}],
        tool_ids=["gdrive"], user_email="me@example.com",
        tool_mode="read_only",
        usage=agent_runner.agent_escalation.TurnUsage(run_id="run-1"))

    assert [c["status"] for c in calls] == [agent_activity.STEP_FAILED]


async def test_the_loop_records_a_handoff_target_from_the_outcome(monkeypatch):
    calls = _recorded(monkeypatch)
    await _two_rounds(monkeypatch, "ask_colleague")

    async def handoff(call, user_email, tool_ids, agent_id, outcome=None):
        outcome.target_agent_id = "agent-iris"
        return outcome.ok("Iris says: under Q3.")

    monkeypatch.setattr(agent_runner, "execute_tool_call", handoff)

    await agent_runner._chat(
        token="t", model="agent-nora",
        messages=[{"role": "user", "content": "q"}],
        tool_ids=["colleague"], user_email="me@example.com",
        tool_mode="read_only",
        usage=agent_runner.agent_escalation.TurnUsage(run_id="run-1"))

    assert calls == [{"run": "run-1", "agent": "agent-nora",
                      "tool": "ask_colleague",
                      "status": agent_activity.STEP_OK,
                      "target": "agent-iris"}]
