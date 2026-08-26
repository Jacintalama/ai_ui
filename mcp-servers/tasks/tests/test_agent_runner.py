"""Running a schedule as one of the user's AI agents.

The agent has to act as the schedule's OWNER, with the owner's own tools, and
it has to survive the agent being deleted from the web after the schedule was
made. Every path ends in a delivered message: a schedule nobody is watching
that silently produces nothing is worse than one that says it broke.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

import agent_runner

# Captured before the autouse `wired` fixture below replaces agent_runner._chat
# with a mock, so the two tests that exercise the real HTTP parsing logic can
# still reach it.
_real_chat = agent_runner._chat


def _sched(**over):
    base = dict(id="sched-1", user_email="owner@example.com",
                agent_id="agent-triage-0002", name="Morning triage",
                prompt="Sort my unread mail.", last_result=None,
                last_run_status="completed")
    base.update(over)
    return SimpleNamespace(**base)


AGENT_ROW = {"id": "agent-triage-0002", "name": "Triage",
             "meta": {"toolIds": ["gmail"]}}

# A second, different agent, so the fixture's listing always has more than
# one row. A lookup that grabs a row by position (e.g. `agents[0] if agents
# else None`) instead of matching sched.agent_id would pick this one -- and a
# fixture list of exactly one row can never tell that apart from a correct
# lookup, since index 0 and "the matching one" are the same row either way.
OTHER_AGENT_ROW = {"id": "agent-decoy-0099", "name": "Decoy",
                   "meta": {"toolIds": ["calendar"]}}


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    """Replace every network seam. Nothing here touches a socket."""
    owui_user_id_for = AsyncMock(return_value="owui-owner-1")
    monkeypatch.setattr(agent_runner, "_owui_user_id_for", owui_user_id_for)
    monkeypatch.setattr(agent_runner, "mint_owui_token",
                        lambda user_id, ttl_seconds=60: "minted-token")
    # Decoy listed FIRST: a lookup that used position instead of matching
    # sched.agent_id would return the decoy, not the named agent.
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([OTHER_AGENT_ROW, AGENT_ROW], False)))
    chat = AsyncMock(return_value=("Two need a reply today.", []))
    monkeypatch.setattr(agent_runner, "_chat", chat)
    return SimpleNamespace(chat=chat, owui_user_id_for=owui_user_id_for)


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
        return_value=([{"id": "agent-triage-0002", "name": "Triage",
                        "meta": {"toolIds": []}}], False)))

    await agent_runner.run_agent(_sched())

    assert wired.chat.await_args.kwargs["tool_ids"] is None


async def test_identity_is_resolved_from_the_schedules_own_email(wired):
    """The `wired` fixture stubs _owui_user_id_for's answer but, on its own,
    never checks what it was asked. Resolving a hardcoded email, or
    sched.name instead of sched.user_email, would still return the same
    stubbed owner id and pass every other test in this file."""
    sched = _sched(user_email="owner-of-this-one@example.com",
                    name="Not an email address")

    await agent_runner.run_agent(sched)

    wired.owui_user_id_for.assert_awaited_once_with(
        "owner-of-this-one@example.com")


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

    # Two mints, both long-lived: the listing loop's own worst case (up to
    # 5 sequential 30s-timeout requests) can outlast a short TTL too, so it
    # now carries the same lifetime as the chat token.
    assert len(ttls) == 2
    assert ttls[0] >= agent_runner.HTTP_TIMEOUT_SECONDS, "listing token covers its own worst case"
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


async def test_a_failed_previous_run_is_not_carried_forward(wired):
    """_finalize_run stores last_result for every status, including this
    runner's own synthetic failure sentences. Handing that back as "what you
    produced last time" would have the agent echo its own failure message,
    and it does that on every run after the first."""
    await agent_runner.run_agent(_sched(
        last_result="The agent could not finish this run. It will try "
                    "again at the next scheduled time.",
        last_run_status="failed"))

    msgs = wired.chat.await_args.kwargs["messages"]
    assert len(msgs) == 1, msgs
    sent = "".join(m["content"] for m in msgs)
    assert "could not finish" not in sent


async def test_a_deleted_agent_still_delivers_something(wired, monkeypatch):
    """The agent was removed from the web after the schedule was made. The run
    must still produce a message that says so. The listing was complete
    (truncated=False), so this is a real "does not exist", and the message
    must say something a person can actually act on: there is no edit UI, so
    it must not send them looking for one."""
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([], False)))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert "no longer" in result.lower() or "gone" in result.lower()
    assert "delete" in result.lower(), "must point at something the owner can do"
    wired.chat.assert_not_called()


async def test_a_truncated_listing_does_not_claim_the_agent_is_gone(
    wired, monkeypatch,
):
    """A listing that was cut short before it could see every agent is not
    proof the agent does not exist -- it may simply be on a page this call
    never reached. Saying "no longer exists" here would be a false claim."""
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([], True)))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert "no longer exists" not in result.lower()
    assert result.strip() != ""
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


async def test_a_refusal_note_is_appended_to_the_delivered_answer(wired):
    """_chat reports what it declined as a note rather than raising. A run
    that quietly dropped part of its job and reported plain success would be
    worse than one that said so, so run_agent must fold any notes into the
    delivered result rather than discard them."""
    wired.chat.return_value = (
        "Sorted your inbox.",
        ["Declined to run send_email, because this schedule is set to "
         "read only."])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed"
    assert "Sorted your inbox." in result
    assert "Declined to run send_email" in result


@respx.mock
async def test_chat_runs_a_requested_tool_and_returns_the_final_answer(
    monkeypatch,
):
    """The shape measured on production: the first completion comes back with
    empty content, finish_reason "tool_calls", and a tool_calls array. Open
    WebUI never runs the tool itself for an API caller, so _chat has to run
    it and post the result back to get a real answer."""
    calls = {"n": 0}

    def respond(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": "",
                               "tool_calls": [{"id": "1", "type": "function",
                                              "function": {
                                                  "name": "gmail_search",
                                                  "arguments": "{}"}}]},
                }]})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop",
                        "message": {"role": "assistant",
                                   "content": "Found 2 matching emails."}}]})

    respx.post(f"{agent_runner._base_url()}/api/chat/completions").mock(
        side_effect=respond)
    ex = AsyncMock(return_value="2 matches")
    monkeypatch.setattr(agent_runner, "execute_tool_call", ex)

    answer, notes = await _real_chat(
        token="t", model="m", messages=[{"role": "user", "content": "hi"}],
        tool_ids=["gmail"], user_email="owner@example.com",
        tool_mode="read_only")

    assert answer == "Found 2 matching emails."
    assert notes == []
    ex.assert_awaited_once()


@respx.mock
async def test_chat_with_plain_empty_content_still_returns_empty_string():
    """Without a tool_calls array, empty content is just an empty answer and
    no notes, not something refused."""
    respx.post(f"{agent_runner._base_url()}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": ""}}]}))

    out = await _real_chat(token="t", model="m",
                           messages=[{"role": "user", "content": "hi"}],
                           tool_ids=None, user_email="owner@example.com",
                           tool_mode="read_only")

    assert out == ("", [])


async def test_the_minted_token_is_never_returned_in_the_result(wired):
    """This project has already logged a bot token once."""
    status, result, extras = await agent_runner.run_agent(_sched())

    assert "minted-token" not in result
    assert "minted-token" not in repr(extras)
