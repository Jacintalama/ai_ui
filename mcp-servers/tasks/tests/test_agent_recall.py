"""What an agent starts a turn knowing.

The recall block rides at the end of the identity line so every surface that
builds a turn through _turn_for carries it: the main chat pipe, the panel,
Discord, Slack and Telegram.
"""
from unittest.mock import AsyncMock

import pytest

import agent_memory
import routes_agent_turn as rt


def _agent():
    return {"id": "agent-1", "name": "Ada", "meta": {"toolIds": ["gmail"]}}


def test_an_empty_block_leaves_the_identity_line_byte_identical():
    before = rt._identity_line(_agent(), ["Ada"])
    after = rt._identity_line(_agent(), ["Ada"], memory="")
    assert before == after


def test_the_block_is_appended_after_everything_else():
    line = rt._identity_line(_agent(), ["Ada"], memory="Known about this person:\n- x")
    content = line["content"]
    assert content.endswith("Known about this person:\n- x")
    assert "\n\nKnown about this person" in content


async def test_turn_for_reads_memory_and_hands_it_to_the_line(monkeypatch):
    seen = {}

    async def fake_run(user_email, agent_id, messages):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(return_value="Known about this person:\n- likes tea"))
    await rt._turn_for("o@example.com", _agent(),
                       [{"role": "user", "content": "hello there"}], ["Ada"])
    system = seen["messages"][0]
    assert system["role"] == "system"
    assert "likes tea" in system["content"]


async def test_a_schedule_run_carries_the_block_as_the_leading_system_message(monkeypatch):
    import agent_runner

    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([{"id": "agent-1", "name": "Ada",
                                                   "meta": {"toolIds": []}}], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_runner.agent_activity, "start_run", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(return_value="Known about this person:\n- likes tea"))
    import routes_agent_turn
    monkeypatch.setattr(routes_agent_turn, "tools_for_agent", AsyncMock(return_value=[]))

    class Sched:
        id = "s1"; agent_id = "agent-1"; user_email = "o@example.com"
        prompt = "Write the weekly review."; last_result = ""; last_run_status = None
        tool_mode = "read_only"

    status, _result, _extras = await agent_runner.run_agent(Sched())
    assert status == "completed"
    first = seen["messages"][0]
    assert first["role"] == "system" and "likes tea" in first["content"]
    assert seen["messages"][-1]["content"] == "Write the weekly review."
