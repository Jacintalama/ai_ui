"""The loop that finally lets an agent do something.

Every test drives agent_runner._chat with a fake Open WebUI, because the
real one needs a model. What matters is the bookkeeping: that a result gets
handed back, that a refusal is explained rather than silently dropped, and
that the loop always ends.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

import agent_runner


def _tool_call(name, cid="call_1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": "{}"}}


def _reply(content=None, calls=None):
    msg = {"content": content or "", "tool_calls": calls or None}
    return {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}


async def test_a_read_tool_is_executed_and_its_result_fed_back():
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("list_unread_emails")])
        return _reply(content="You have 4 unread emails.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert answer == "You have 4 unread emails."
    assert notes == []
    ex.assert_awaited_once()
    assert ex.await_args.args[1] == "owner@example.com", "ran as the wrong user"
    # The second request must carry the tool result back.
    second = posts[1]["messages"]
    assert any(m.get("role") == "tool" and "4 unread" in m.get("content", "")
               for m in second)


async def test_a_write_tool_is_refused_in_read_only_and_explained():
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="I could not send it.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    ex.assert_not_awaited(), "read_only must not execute a write tool"
    assert notes and "send_email" in notes[0]
    assert answer == "I could not send it."


async def test_a_write_tool_runs_in_full_mode():
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="Sent.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="sent")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="full")

    ex.assert_awaited_once()
    assert answer == "Sent."


async def test_a_missing_mode_is_treated_as_read_only():
    """Every schedule that predates this feature has no mode at all."""
    async def fake_post(payload, token):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()) as ex:
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com", tool_mode=None)

    ex.assert_not_awaited()


async def test_every_call_in_one_turn_is_executed():
    async def fake_post(payload, token):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_tool_call("list_unread_emails", "a"),
                                 _tool_call("search_emails", "b")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="r")) as ex:
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert ex.await_count == 2


async def test_the_loop_stops_at_the_cap_and_says_so():
    """A model that keeps asking must not spin forever."""
    async def fake_post(payload, token):
        return _reply(calls=[_tool_call("list_unread_emails")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="r")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert ex.await_count <= agent_runner.MAX_TOOL_ITERATIONS
    assert any("stopped" in n.lower() for n in notes)
