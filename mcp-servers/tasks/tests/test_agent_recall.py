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
