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
                last_run_status="completed", tool_mode=None)
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


async def test_chat_is_called_with_the_schedules_own_user_email(wired):
    """F1: _chat's user_email is what execute_tool_call runs every tool as.
    A hardcoded string, or the owui user id (`owner`, an in-scope local at
    the call site and an easy typo for sched.user_email), would still make
    every other test in this file pass -- none of them checks this kwarg's
    actual value. This is the schedule's own email, not the owui user id
    ('owui-owner-1' from the `wired` fixture) and not anything else."""
    sched = _sched(user_email="specific-owner@example.com")

    await agent_runner.run_agent(sched)

    assert (wired.chat.await_args.kwargs["user_email"]
            == "specific-owner@example.com")


@pytest.mark.parametrize("mode", ["full", "read_only"])
async def test_the_schedules_tool_mode_reaches_chat(wired, mode):
    """F2: a hardcoded tool_mode at the run_agent seam would silently turn
    every read_only schedule into full access. Two values are checked, not
    just 'full', so a hardcode to either one is caught by the other case."""
    await agent_runner.run_agent(_sched(tool_mode=mode))

    assert wired.chat.await_args.kwargs["tool_mode"] == mode


async def test_a_schedule_with_no_tool_mode_attribute_passes_none(wired):
    """Schedules from before this column existed have no tool_mode
    attribute at all, not merely one set to None. getattr(sched,
    'tool_mode', None) has to be what's used, not a plain sched.tool_mode
    that would raise, and not a hardcoded value that would ignore the
    schedule entirely."""
    sched = _sched()
    del sched.tool_mode
    assert not hasattr(sched, "tool_mode")

    await agent_runner.run_agent(sched)

    assert wired.chat.await_args.kwargs["tool_mode"] is None


async def test_the_cap_note_reaches_the_owner_even_with_an_empty_answer(wired):
    """F4: _chat's own test (test_the_loop_stops_at_the_cap_and_says_so)
    only proves the note exists inside _chat's return value. Without this,
    run_agent's empty-answer check fires first and throws the note away
    before the owner ever sees it -- so five rounds of real tool use in a
    full-mode schedule could complete and the stored result would say only
    "The agent returned an empty answer.", with no record of what ran."""
    wired.chat.return_value = (
        "",
        ["Stopped after 5 rounds of tool use, so this answer may be "
         "incomplete."])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed"
    assert "stopped after 5 rounds" in result.lower()


async def test_a_refusal_note_reaches_the_owner_even_with_an_empty_answer(wired):
    """F4: the same discard bug, but for an ordinary refusal rather than the
    iteration cap -- an empty final answer must not swallow what was
    declined."""
    wired.chat.return_value = (
        "",
        ["Declined to run send_email, because this schedule is set to "
         "read only."])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed"
    assert "Declined to run send_email" in result


async def test_a_genuinely_empty_answer_with_no_notes_still_fails(wired):
    """The fix for F4 must not turn every empty answer into a success --
    only one that carries notes explaining what happened."""
    wired.chat.return_value = ("", [])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert result.strip() != ""


# --- the agent's level is a ceiling over the schedule's tool_mode ----------

def _sched(agent_id=None, tool_mode=None, email=None, **over):
    """Helper for schedule tests. Backwards compatible with existing tests."""
    # Use new-style defaults for explicit tool_mode, old-style otherwise
    using_new_style = 'tool_mode' in over or tool_mode is not None

    if agent_id is None:
        agent_id = "agent-1" if using_new_style else "agent-triage-0002"
    if email is None:
        email = "owner@example.com"
    # tool_mode stays as passed or None

    base = dict(id="sched-1", user_email=email,
                agent_id=agent_id, name="Morning triage",
                prompt="Sort my unread mail.", last_result=None,
                last_run_status="completed", tool_mode=tool_mode)
    base.update(over)

    class S:
        pass
    s = S()
    for k, v in base.items():
        setattr(s, k, v)
    return s


def _agent_row(access=None):
    meta = {"toolIds": ["gmail"]}
    if access is not None:
        meta["access"] = access
    return {"id": "agent-1", "name": "Scout", "meta": meta}


@pytest.mark.parametrize("access,expected_mode", [
    ("read", "read_only"),   # the agent narrows a full schedule
    ("ask", "read_only"),    # nobody is there to ask at 3am
    ("all", "full"),         # both agree
    (None, "full"),          # no opinion: exactly today's behaviour
])
async def test_the_agent_level_caps_a_full_schedule(access, expected_mode,
                                                    monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row(access)], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)

    status, _result, _extras = await agent_runner.run_agent(
        _sched(tool_mode="full"))

    assert status == "completed"
    assert seen["tool_mode"] == expected_mode


async def test_a_read_only_schedule_still_caps_an_all_access_agent(monkeypatch):
    """The ceiling runs one way. A schedule may narrow, never widen."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("all")], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)

    await agent_runner.run_agent(_sched(tool_mode="read_only"))
    assert seen["tool_mode"] == "read_only"


async def test_an_asking_agent_on_a_schedule_is_told_why(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("ask")], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)

    await agent_runner.run_agent(_sched(tool_mode="full"))
    assert seen["refusal_reason"] == "a scheduled run has nobody to ask"


async def test_an_approval_escaping_into_a_schedule_is_reported_not_swallowed(
        monkeypatch):
    """effective_mode never hands a schedule "ask", so this cannot happen
    today. If it ever does, the owner must get a sentence that names the
    cause rather than the generic "could not finish this run"."""
    import agent_access

    async def boom(**kwargs):
        raise agent_access.ApprovalRequired([], [])

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("all")], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", boom)

    status, result, _extras = await agent_runner.run_agent(_sched())
    assert status == "failed"
    assert "nobody to ask" in result
