"""The floor learns a tool started the moment it starts."""
import pytest

import agent_handoff
import agent_tools


@pytest.fixture
def sent(monkeypatch):
    got = []
    monkeypatch.setattr(agent_tools.agent_events, "publish",
                        lambda event, **kw: got.append((event, kw)))
    return got


def _call(name):
    return {"function": {"name": name, "arguments": "{}"}}


async def test_a_tool_call_inside_a_run_is_announced(sent):
    # HANDOFF_TOOL with allowed_native_tools=None is refused before any
    # lookup, so this runs with no network and no database.
    async with agent_handoff.began("run-1"):
        await agent_tools.execute_tool_call(
            _call(agent_tools.HANDOFF_TOOL), "me@example.com",
            allowed_native_tools=None, agent_id="agent-a")
    assert sent == [("tool_started", {"agent_id": "agent-a",
                                      "user_email": "me@example.com",
                                      "tool": agent_tools.HANDOFF_TOOL})]


async def test_a_tool_call_outside_any_run_is_not_announced(sent):
    await agent_tools.execute_tool_call(
        _call(agent_tools.HANDOFF_TOOL), "me@example.com",
        allowed_native_tools=None, agent_id="agent-a")
    assert sent == []


async def test_a_call_that_names_no_tool_is_not_announced(sent):
    async with agent_handoff.began("run-1"):
        await agent_tools.execute_tool_call(
            _call("  "), "me@example.com", agent_id="agent-a")
    assert sent == []
