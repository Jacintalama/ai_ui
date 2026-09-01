"""Picking a held turn back up once the owner has answered.

The dangerous half of the approval flow. Everything here is about the window
between the question and the answer: the agent can be edited, the level can
change, and the same record must never run twice.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import agent_access
import routes_agent_turn as rt


def _agent(access="ask"):
    return {"id": "agent-1", "name": "Scout",
            "meta": {"toolIds": ["gmail"], "access": access}}


def _body(approved=True, **over):
    class B:
        user_email = "owner@example.com"
        agent_id = "agent-1"
        conversation = [
            {"role": "user", "content": "send it"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1",
                             "function": {"name": "send_email",
                                          "arguments": "{}"}}]},
        ]
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "send_email", "arguments": "{}"}}]
    b = B()
    b.approved = approved
    for k, v in over.items():
        setattr(b, k, v)
    return b


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-2"))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())


async def test_an_approved_call_runs_and_the_answer_comes_back(monkeypatch):
    async def fake_chat(**kwargs):
        return "Sent it.", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    out = await rt.resume(_body(approved=True), x_internal_secret="s")

    ex.assert_awaited_once()
    assert out["answer"] == "Sent it."


async def test_the_tool_result_is_fed_back_before_the_model_is_asked_again(
        monkeypatch):
    """Every tool_call in the assistant message needs a matching tool message
    or the next completion is rejected outright."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt, "execute_tool_call",
                        AsyncMock(return_value="sent"))

    await rt.resume(_body(approved=True), x_internal_secret="s")

    tool_msgs = [m for m in seen["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1"]
    assert tool_msgs[0]["content"] == "sent"


async def test_a_refusal_runs_nothing_but_still_lets_the_agent_explain(
        monkeypatch):
    """Going silent would be worse. The agent gets told it was refused and
    answers in its own words."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "Alright, I did not send it.", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock()
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    out = await rt.resume(_body(approved=False), x_internal_secret="s")

    ex.assert_not_awaited()
    tool_msgs = [m for m in seen["messages"] if m.get("role") == "tool"]
    assert rt.REFUSED_BY_OWNER in tool_msgs[0]["content"]
    assert out["answer"] == "Alright, I did not send it."


async def test_an_agent_downgraded_to_read_only_does_not_get_its_write(
        monkeypatch):
    """The level is re-read on resume, not trusted from when the question was
    asked. Somebody who has second thoughts and changes the setting has
    changed the setting."""
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("read")], False)))
    ex = AsyncMock()
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    out = await rt.resume(_body(approved=True), x_internal_secret="s")

    ex.assert_not_awaited()
    assert "read only" in out["answer"]


async def test_a_deleted_agent_does_not_get_its_write(monkeypatch):
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    ex = AsyncMock()
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    with pytest.raises(HTTPException):
        await rt.resume(_body(approved=True), x_internal_secret="s")
    ex.assert_not_awaited()


async def test_a_resumed_turn_can_ask_again(monkeypatch):
    """A model that wants a second write after the first one landed has to be
    able to ask about that one too."""
    convo = [{"role": "tool", "tool_call_id": "c1", "content": "sent"}]
    calls = [{"id": "c2", "function": {"name": "delete_message"}}]

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(convo, calls)

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt, "execute_tool_call",
                        AsyncMock(return_value="sent"))

    out = await rt.resume(_body(approved=True), x_internal_secret="s")
    assert out["pending"]["calls"] == calls


async def test_all_access_resumes_too(monkeypatch):
    """An agent moved from ask to all between question and answer should not
    be stuck: it is now MORE permitted, not less."""
    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    await rt.resume(_body(approved=True), x_internal_secret="s")
    ex.assert_awaited_once()


async def test_the_tools_are_still_resolved_here_not_taken_from_the_caller(
        monkeypatch):
    """Same rule as the turn endpoint: the caller names the agent, this names
    the tools. execute_tool_call is scoped by them."""
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))

    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    await rt.resume(_body(approved=True), x_internal_secret="s")
    assert ex.await_args.args[2] == ["gmail"]


async def test_a_spoofed_tool_ids_on_the_request_body_is_ignored(monkeypatch):
    """The guarantee above must not rest only on ResumeIn happening to have
    no tool_ids field. A future edit like `getattr(body, "tool_ids", None) or
    tools` would pass every other test here while handing the caller the
    keys. Set the attribute directly on the request object and assert
    execute_tool_call still only ever saw the agent's own resolved tools."""
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))

    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    body = _body(approved=True)
    body.tool_ids = ["gmail", "scheduler", "server:mcp-proxy"]

    await rt.resume(body, x_internal_secret="s")
    assert ex.await_args.args[2] == ["gmail"]


async def test_the_run_is_recorded_as_a_channel_run(monkeypatch):
    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt, "execute_tool_call", AsyncMock(return_value="ok"))

    await rt.resume(_body(approved=True), x_internal_secret="s")
    assert (rt.agent_activity.start_run.await_args.args[2]
            == rt.agent_activity.SOURCE_CHANNEL)
