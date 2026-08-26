"""Running a schedule as one of the user's AI agents.

The agent has to act as the schedule's OWNER, with the owner's own tools, and
it has to survive the agent being deleted from the web after the schedule was
made. Every path ends in a delivered message: a schedule nobody is watching
that silently produces nothing is worse than one that says it broke.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import agent_runner


def _sched(**over):
    base = dict(id="sched-1", user_email="owner@example.com",
                agent_id="agent-triage-0002", name="Morning triage",
                prompt="Sort my unread mail.", last_result=None)
    base.update(over)
    return SimpleNamespace(**base)


AGENT_ROW = {"id": "agent-triage-0002", "name": "Triage",
             "meta": {"toolIds": ["gmail"]}}


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    """Replace every network seam. Nothing here touches a socket."""
    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="owui-owner-1"))
    monkeypatch.setattr(agent_runner, "mint_owui_token",
                        lambda user_id, ttl_seconds=60: "minted-token")
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=[AGENT_ROW]))
    chat = AsyncMock(return_value="Two need a reply today.")
    monkeypatch.setattr(agent_runner, "_chat", chat)
    return SimpleNamespace(chat=chat)


async def test_it_runs_the_named_agent(wired):
    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed"
    assert "reply today" in result
    assert wired.chat.await_args.kwargs["model"] == "agent-triage-0002"


async def test_it_sends_the_agents_own_tools(wired):
    """Open WebUI attaches a model's tools only for its own UI. An API caller
    that does not ask gets none, and the agent arrives unable to do anything."""
    await agent_runner.run_agent(_sched())

    assert wired.chat.await_args.kwargs["tool_ids"] == ["gmail"]


async def test_an_agent_with_no_tools_sends_none(wired, monkeypatch):
    """None is not the same as an empty list, which reads as an explicit
    request for no tools."""
    monkeypatch.setattr(agent_runner, "_list_agents", AsyncMock(
        return_value=[{"id": "agent-triage-0002", "name": "Triage",
                       "meta": {"toolIds": []}}]))

    await agent_runner.run_agent(_sched())

    assert wired.chat.await_args.kwargs["tool_ids"] is None


async def test_it_runs_as_the_owner_not_anyone_else(wired, monkeypatch):
    """A schedule belongs to one person, reads their mail, and runs whether or
    not they are online. Running as the wrong identity would read somebody
    else's mailbox and look completely correct."""
    user_ids = []

    def spy_mint(user_id, ttl_seconds=60):
        user_ids.append(user_id)
        return f"token-{len(user_ids)}"

    monkeypatch.setattr(agent_runner, "mint_owui_token", spy_mint)

    await agent_runner.run_agent(_sched())

    assert user_ids == ["owui-owner-1", "owui-owner-1"], "both mints use the owner"


async def test_the_token_outlives_a_slow_tool_call(wired, monkeypatch):
    """The chat phase requires a long-lived token. It is minted immediately
    before the call to guarantee it covers the full timeout window."""
    ttls = []

    def spy_mint(user_id, ttl_seconds=60):
        ttls.append(ttl_seconds)
        return f"token-{ttl_seconds}"

    monkeypatch.setattr(agent_runner, "mint_owui_token", spy_mint)

    await agent_runner.run_agent(_sched())

    # Two mints: first for listing (short), second for chat (long).
    assert len(ttls) == 2
    assert ttls[0] == 60, "listing token has standard short TTL"
    assert ttls[1] >= agent_runner.HTTP_TIMEOUT_SECONDS, "chat token covers the timeout"


async def test_the_previous_result_is_carried_forward(wired):
    """A daily digest that repeats itself is useless, and the CLI path this
    replaces kept a memory between runs."""
    await agent_runner.run_agent(_sched(last_result="Yesterday: 3 invoices."))

    sent = "".join(m["content"] for m in wired.chat.await_args.kwargs["messages"])
    assert "3 invoices" in sent


async def test_a_huge_previous_result_is_trimmed(wired):
    await agent_runner.run_agent(_sched(last_result="x" * 9000))

    sent = "".join(m["content"] for m in wired.chat.await_args.kwargs["messages"])
    assert len(sent) < 4000, "the whole of last_result was pasted in"


async def test_the_first_run_carries_nothing(wired):
    await agent_runner.run_agent(_sched(last_result=None))

    msgs = wired.chat.await_args.kwargs["messages"]
    assert len(msgs) == 1, msgs


async def test_a_deleted_agent_still_delivers_something(wired, monkeypatch):
    """The agent was removed from the web after the schedule was made. The run
    must still produce a message that says so."""
    monkeypatch.setattr(agent_runner, "_list_agents", AsyncMock(return_value=[]))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert "no longer" in result.lower() or "gone" in result.lower()
    wired.chat.assert_not_called()


async def test_an_owner_with_no_account_fails_readably(wired, monkeypatch):
    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value=None))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert result.strip() != ""
    wired.chat.assert_not_called()


async def test_a_model_failure_is_reported_not_raised(wired):
    """_finalize_run dispatches this detached, so a raise would vanish and
    leave the schedule stuck on running."""
    wired.chat.side_effect = RuntimeError("model down")

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert result.strip() != ""


async def test_the_minted_token_is_never_returned_in_the_result(wired):
    """This project has already logged a bot token once."""
    status, result, extras = await agent_runner.run_agent(_sched())

    assert "minted-token" not in result
    assert "minted-token" not in repr(extras)
