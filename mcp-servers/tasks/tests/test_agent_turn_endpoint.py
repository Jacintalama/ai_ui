"""One agent turn, asked for by the chat gateway.

The gateway says WHICH agent. This service decides what that agent may touch.
That split is the point of the endpoint: tool_ids is the gate on which native
tools may execute, so a caller that could name them would be deciding its own
permissions.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import agent_access
import routes_agent_turn as rt


def _agent(access=None, tools=("gmail",)):
    meta = {"toolIds": list(tools)}
    if access is not None:
        meta["access"] = access
    return {"id": "agent-1", "name": "Scout", "meta": meta}


def _body(**over):
    class B:
        user_email = "owner@example.com"
        agent_id = "agent-1"
        messages = [{"role": "user", "content": "q"}]
    b = B()
    for k, v in over.items():
        setattr(b, k, v)
    return b


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-1"))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())


async def test_the_endpoint_resolves_the_agents_own_tools(monkeypatch):
    """A caller must not be able to name tool_ids. It is the gate on which
    native tools may execute, so naming it outside this service would move
    the decision to the wrong side of the wall."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all", ["gmail"])], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    out = await rt.turn(_body(), x_internal_secret="s")

    assert out == {"answer": "done", "notes": []}
    assert seen["tool_ids"] == ["gmail"]
    assert seen["user_email"] == "owner@example.com"


@pytest.mark.parametrize("access,expected", [
    ("read", agent_access.MODE_READ_ONLY),
    ("ask", agent_access.MODE_ASK),
    ("all", agent_access.MODE_FULL),
    (None, agent_access.MODE_READ_ONLY),
])
async def test_the_agents_level_decides_the_mode(access, expected, monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent(access)], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")
    assert seen["tool_mode"] == expected


async def test_the_refusal_never_mentions_schedules(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("read")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")
    assert "schedule" not in seen["refusal_reason"]


async def test_a_channel_gets_the_shorter_leash(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")
    assert seen["max_iterations"] == rt.CHANNEL_MAX_TOOL_ITERATIONS
    assert seen["timeout"] == rt.CHANNEL_HTTP_TIMEOUT_SECONDS


async def test_an_agent_that_wants_approval_comes_back_as_pending(monkeypatch):
    convo = [{"role": "assistant", "content": "", "tool_calls": []}]
    calls = [{"id": "c1", "function": {"name": "send_email"}}]

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(convo, calls)

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("ask")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    out = await rt.turn(_body(), x_internal_secret="s")

    assert "answer" not in out
    assert out["pending"]["calls"] == calls
    assert out["pending"]["agent_id"] == "agent-1"
    # Carried so the resume can check that the person answering is the person
    # who was asked. The state key is per chat, not per person.
    assert out["pending"]["user_email"] == "owner@example.com"


async def test_a_stored_conversation_is_trimmed(monkeypatch):
    """It holds every tool result from the turn and lands in a JSON column,
    so an uncapped record grows to whatever the agent happened to read."""
    big = "x" * (rt.PENDING_CONTENT_CHARS * 3)
    convo = [{"role": "tool", "tool_call_id": "c0", "content": big}]

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(convo, [{"id": "c1"}])

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("ask")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    out = await rt.turn(_body(), x_internal_secret="s")
    stored = out["pending"]["conversation"][0]["content"]
    assert len(stored) <= rt.PENDING_CONTENT_CHARS + 100


async def test_an_unknown_agent_is_a_404_not_a_crash(monkeypatch):
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    with pytest.raises(HTTPException) as caught:
        await rt.turn(_body(), x_internal_secret="s")
    assert caught.value.status_code == 404


async def test_a_truncated_listing_is_not_read_as_a_missing_agent(monkeypatch):
    """"Not in what we fetched" is not "does not exist". Saying the agent is
    gone would send somebody deleting a schedule that was fine."""
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], True)))
    with pytest.raises(HTTPException) as caught:
        await rt.turn(_body(), x_internal_secret="s")
    assert caught.value.status_code == 503


async def test_the_run_is_recorded_as_a_channel_run(monkeypatch):
    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")

    rt.agent_activity.start_run.assert_awaited_once()
    assert (rt.agent_activity.start_run.await_args.args[2]
            == rt.agent_activity.SOURCE_CHANNEL)
    rt.agent_activity.finish_run.assert_awaited_once()


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")

    monkeypatch.setattr(rt, "_require_internal", deny)
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    with pytest.raises(HTTPException) as caught:
        await rt.turn(_body(), x_internal_secret="wrong")
    assert caught.value.status_code == 403
