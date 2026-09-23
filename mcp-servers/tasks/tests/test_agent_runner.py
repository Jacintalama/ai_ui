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

import agent_memory
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
    """Replace the seams run_agent reaches for, so no test here calls out.

    recall_block joined that list when scheduled runs started carrying
    agent memory. It fails open, so patched or not the answer is the
    same, but unpatched every test in this file waits on a database
    this machine does not have: measured at about two seconds a test.

    graph_block joined it on 2026-09-23 for exactly the same reason, when
    a scheduled run started carrying the whole brief rather than the
    memory block alone. It also fails open, and it also waits on that
    database first.

    The run bookkeeping in agent_activity opens its own session and is
    still unpatched, so some of that cost remains. Nothing here asserts
    on it.
    """
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
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(agent_runner.agent_graph, "graph_block",
                        AsyncMock(return_value=""))
    return SimpleNamespace(chat=chat, owui_user_id_for=owui_user_id_for)


def _carried(msgs: list[dict]) -> list[dict]:
    """The conversation without the brief.

    Every scheduled run leads with one since 2026-09-23. It is the same
    block on every run, so it is never what a test about what this run
    carries forward is asking about. tests/test_agent_brief.py pins the
    brief itself.
    """
    assert msgs and msgs[0]["role"] == "system", msgs
    return msgs[1:]


async def test_it_runs_the_named_agent(wired):
    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed"
    assert "reply today" in result
    assert wired.chat.await_args.kwargs["model"] == "agent-triage-0002"


async def test_it_sends_the_agents_own_tools_first(wired):
    """Open WebUI attaches a model's tools only for its own UI. An API caller
    that does not ask gets none, and the agent arrives unable to do anything.

    The agent's own picks lead the list. They used to be the WHOLE list here,
    which is what made a scheduled agent weaker than the same agent in chat.
    """
    await agent_runner.run_agent(_sched())

    sent = wired.chat.await_args.kwargs["tool_ids"]
    assert sent[0] == "gmail", sent
    assert "gmail" in sent


async def test_a_schedule_reaches_what_the_same_agent_reaches_in_chat(wired):
    """Resolves through routes_agent_turn.tools_for_agent, the one the chat
    path uses, rather than reading meta["toolIds"] raw.

    Measured on production 2026-09-10: the same agent had twelve tools in chat
    and one on a schedule, and that one was the connected-apps umbrella with
    nothing behind it. It could read nothing, so it wrote its weekly report
    from nothing, while its card still said "Every tool you have".
    """
    await agent_runner.run_agent(_sched())

    sent = wired.chat.await_args.kwargs["tool_ids"]
    assert len(sent) > 1, (
        "the schedule got only the agent's raw toolIds: %r" % (sent,))


async def test_an_empty_tool_list_is_not_a_request_for_no_tools(wired, monkeypatch):
    """A deliberate reversal, recorded because the two surfaces disagreed.

    This test used to assert the opposite, and said why: "None is not the same
    as an empty list, which reads as an explicit request for no tools." The
    chat path had already decided the other way, in as many words: "Picking
    nothing is not a request for nothing. Somebody who chose the narrow option
    and then unticked every box has not finished choosing, and an agent with
    no tools at all would simply look broken."

    Both cannot be right for the same agent. The chat path's reading wins,
    because it is the newer one, because it came with the toolScope setting
    that lets somebody say "only these" explicitly, and because an empty list
    is far more often an unfinished thought than an instruction.

    What an agent may DO on a schedule is unchanged and still narrower: a
    schedule's tool_mode defaults to read_only, and agent_runner refuses every
    write call. This widens what it can READ, which is the axis that was
    accidentally different, not the one that was deliberately narrow.
    """
    monkeypatch.setattr(agent_runner, "_list_agents", AsyncMock(
        return_value=([{"id": "agent-triage-0002", "name": "Triage",
                        "meta": {"toolIds": []}}], False)))

    await agent_runner.run_agent(_sched())

    sent = wired.chat.await_args.kwargs["tool_ids"]
    assert sent, "an empty list still meant no tools at all"


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

    # The carried message alone. Measuring the whole conversation would put
    # the brief's own length inside a limit that is about last_result.
    sent = "".join(m["content"]
                   for m in _carried(wired.chat.await_args.kwargs["messages"]))
    assert len(sent) < 4000, "the whole of last_result was pasted in"


async def test_the_first_run_carries_nothing(wired):
    await agent_runner.run_agent(_sched(last_result=None))

    msgs = _carried(wired.chat.await_args.kwargs["messages"])
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

    msgs = _carried(wired.chat.await_args.kwargs["messages"])
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


async def test_a_schedule_with_no_tool_mode_attribute_runs_read_only(wired):
    """Schedules from before this column existed have no tool_mode
    attribute at all, not merely one set to None. getattr(sched,
    'tool_mode', None) has to be what's used, not a plain sched.tool_mode
    that would raise, and not a hardcoded value that would ignore the
    schedule entirely.

    The effective mode is computed at the run_agent seam now, by
    agent_access.effective_mode, rather than being derived inside _chat from
    a bare None. With no agent level and no schedule tool_mode, that
    computation lands on "read_only" -- the same value _chat used to derive
    from None on its own, so observable behaviour is unchanged."""
    sched = _sched()
    del sched.tool_mode
    assert not hasattr(sched, "tool_mode")

    await agent_runner.run_agent(sched)

    assert wired.chat.await_args.kwargs["tool_mode"] == "read_only"


async def test_the_cap_note_reaches_the_owner_even_with_an_empty_answer(wired):
    """F4: _chat's own test (test_the_loop_stops_at_the_cap_and_says_so)
    only proves the note exists inside _chat's return value. Without this,
    run_agent's empty-answer check fires first and throws the note away
    before the owner ever sees it, with no record of what ran.

    That concern still stands and is still asserted. What changed is the
    STATUS. This used to assert "completed", and on a schedule that is the
    whole problem: the delivered report becomes the note itself, 69
    characters saying the answer may be incomplete, with a green card. Seen
    on the first real weekly review, 2026-09-11. The owner is still told,
    and now told it failed, which is what the card reads.
    """
    wired.chat.return_value = (
        "",
        [agent_runner.RAN_OUT_OF_ROUNDS % 5])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed", (status, result)
    # Still a record of what happened, which is what F4 was protecting.
    assert "ran out of tool rounds" in result.lower()
    assert result.strip(), "the note was swallowed, which is the F4 bug"


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

def _agent_row(access=None):
    """Same id as the module's default _sched()/AGENT_ROW, but with a
    specific meta.access. There is no existing helper by this name, so it
    does not collide with AGENT_ROW; it exists so a test can carry a
    meta.access value AGENT_ROW itself does not have."""
    meta = {"toolIds": ["gmail"]}
    if access is not None:
        meta["access"] = access
    return {"id": "agent-triage-0002", "name": "Scout", "meta": meta}


@pytest.mark.parametrize("access,expected_mode", [
    ("read", "read_only"),   # the agent narrows a full schedule
    ("ask", "read_only"),    # nobody is there to ask at 3am
    ("all", "full"),         # both agree
    (None, "full"),          # no opinion: exactly today's behaviour
])
async def test_the_agent_level_caps_a_full_schedule(wired, monkeypatch,
                                                    access, expected_mode):
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row(access)], False)))

    status, _result, _extras = await agent_runner.run_agent(
        _sched(tool_mode="full"))

    assert status == "completed"
    assert wired.chat.await_args.kwargs["tool_mode"] == expected_mode


async def test_a_read_only_schedule_still_caps_an_all_access_agent(
        wired, monkeypatch):
    """The ceiling runs one way. A schedule may narrow, never widen."""
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("all")], False)))

    await agent_runner.run_agent(_sched(tool_mode="read_only"))

    assert wired.chat.await_args.kwargs["tool_mode"] == "read_only"


async def test_an_asking_agent_on_a_schedule_is_told_why(wired, monkeypatch):
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("ask")], False)))

    await agent_runner.run_agent(_sched(tool_mode="full"))

    assert (wired.chat.await_args.kwargs["refusal_reason"]
            == "a scheduled run has nobody to ask")


async def test_an_approval_escaping_into_a_schedule_is_reported_not_swallowed(
        wired, monkeypatch):
    """effective_mode never hands a schedule "ask", so this cannot happen
    today. If it ever does, the owner must get a sentence that names the
    cause rather than the generic "could not finish this run"."""
    import agent_access

    async def boom(**kwargs):
        raise agent_access.ApprovalRequired([], [])

    monkeypatch.setattr(agent_runner, "_chat", boom)

    status, result, _extras = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert "nobody to ask" in result


# ---------------------------------------------------------------------------
# Running out of tool rounds. Measured on the first real weekly review,
# 2026-09-11: one run used four of five rounds and wrote a proper 1174
# character report; the run a minute before it spent all five and returned 69
# characters, the note saying it had stopped early, reported as "completed".
# On a schedule that note IS the delivered report.
# ---------------------------------------------------------------------------


async def test_stopping_early_with_nothing_to_show_is_a_failure(wired, monkeypatch):
    """It used to report "completed" and deliver the note as the report."""
    monkeypatch.setattr(agent_runner, "_chat", AsyncMock(return_value=(
        "", [agent_runner.RAN_OUT_OF_ROUNDS % 8])))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed", (status, result)
    assert "ran out of tool rounds" in result
    assert "may be incomplete" not in result, (
        "the stub note was delivered as the report")


async def test_stopping_early_WITH_an_answer_still_completes(wired, monkeypatch):
    """The opposite mistake would be worse: a real report thrown away because
    the agent also mentioned it had more it could have read."""
    monkeypatch.setattr(agent_runner, "_chat", AsyncMock(return_value=(
        "**Weekly review**\n\nShipped: the thing.",
        [agent_runner.RAN_OUT_OF_ROUNDS % 8])))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed", (status, result)
    assert "Weekly review" in result
    assert "may be incomplete" in result, "the caveat was dropped"


async def test_an_empty_answer_with_other_notes_still_completes(wired, monkeypatch):
    """Only the ran-out-of-rounds case is a failure. A refusal note carries
    real information about what the agent would not do, and that must still
    reach the owner."""
    monkeypatch.setattr(agent_runner, "_chat", AsyncMock(return_value=(
        "", ["Refused: send_email is a write and this run is read only."])))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed", (status, result)
    assert "Refused" in result


def test_the_schedule_gets_more_rounds_than_a_chat_window():
    """A chat window has somebody waiting at a keyboard; a Friday cron does
    not. The caps are allowed to differ, and the schedule's is the larger."""
    assert agent_runner.MAX_TOOL_ITERATIONS > agent_runner.CHANNEL_MAX_TOOL_ITERATIONS
    # Four rounds were needed for a real weekly review, so anything at or
    # below five leaves a single round of margin, which is what failed.
    assert agent_runner.MAX_TOOL_ITERATIONS >= 8


def test_the_token_outlives_the_whole_loop():
    """Derived, not hardcoded. Raising the cap without raising the token gives
    an agent that dies partway through and reports it as a refusal.

    The free pool counts too. An agent on a free model can spend every id in
    one turn, and each spent id is one more completion of up to the full
    timeout, so the rounds alone stopped describing the worst case the day
    the fallback was added. The token expiring mid-loop is the worst kind of
    failure here: a 401 is deliberately not a provider failure, so it ends
    the run rather than moving to the next model.

    The write-up after the tool cap is in the count as well, the `+ 1`. It
    is the round that carries everything the run read, so it is the one most
    worth not losing, and it is the last thing the person hears from a run
    that spent every round. Leaving it out left the token three minutes
    short of the loop it is supposed to outlive."""
    assert agent_runner.CHAT_TOKEN_TTL_SECONDS >= (
        (agent_runner.MAX_TOOL_ITERATIONS + 1
         + len(agent_runner.FREE_MODELS) - 1)
        * agent_runner.HTTP_TIMEOUT_SECONDS)
    # And the move to the paid model, which can add rounds after the free
    # ones are spent (2026-09-17).
    assert agent_runner.CHAT_TOKEN_TTL_SECONDS >= agent_runner.worst_turn_seconds(
        agent_runner.MAX_TOOL_ITERATIONS, agent_runner.HTTP_TIMEOUT_SECONDS)


def test_the_worst_turn_counts_the_move_to_the_paid_model(monkeypatch):
    """Pinned with numbers, so a formula that quietly drops a term fails."""
    import agent_escalation
    monkeypatch.setattr(agent_runner, "FREE_MODELS", ["a:free", "b:free", "c:free"])
    monkeypatch.setattr(agent_escalation, "PAID_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(agent_escalation, "PAID_EXTRA_ROUNDS", 3)
    # Both shapes can end the same slow way: the paid write-up times out, the
    # turn goes back to the free model it left, and that write-up spends all
    # three free ids at the write-up timeout. The first version of this count
    # stopped at a write-up that answered and said 930 and 3360 (review,
    # 2026-09-17).
    # Chat, moving at the start: 1 free answer at 60 + 7 paid rounds at 90
    # + a 120 paid write-up + 3 free write-ups at 120 = 1170. Moving at the
    # round cap: 7 free rounds at 60 + 3 paid at 90 + 120 + 360 = 1170.
    assert agent_runner.worst_turn_seconds(7, 60) == 1170
    # Schedule, at the round cap: 8 free rounds + 3 paid rounds + a paid
    # write-up + 3 free write-ups, all at 240 = 3600.
    assert agent_runner.worst_turn_seconds(8, 240) == 3600


async def test_a_scheduled_report_carries_no_long_dashes(wired):
    """A report lands in the owner's Discord. The brief forbids long dashes
    and the model used one in 25 of 36 replies anyway, so the schedule path
    scrubs on the way out as well as the chat path."""
    wired.chat.return_value = (
        "**Weekly review** Sep 7\u201311\n\nShipped \u2014 the portfolio.", [])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed", (status, result)
    assert "\u2014" not in result and "\u2013" not in result, result
    assert "Sep 7-11" in result


# ---------------------------------------------------------------------------
# The busy sentence is not a report. It reaches run_agent as ordinary content,
# because that is how the free pool and the free router both report giving up,
# and nothing downstream can tell it from an answer.
# ---------------------------------------------------------------------------


async def test_a_busy_free_pool_is_a_failed_run_not_a_report(wired):
    """Delivered as completed, the busy sentence goes out as the week's
    output, and _messages_for then hands it back next run as "what you
    produced last time", which is the poisoning its docstring describes."""
    wired.chat.return_value = (agent_runner.FREE_POOL_EXHAUSTED, [])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed", (status, result)
    assert result == agent_runner.FREE_POOL_EXHAUSTED


async def test_the_router_busy_sentence_is_a_failed_run_too(wired):
    """Auto (Free) says it differently and shipped as completed until now."""
    wired.chat.return_value = (agent_runner.ROUTER_EXHAUSTED, [])

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed", (status, result)
    assert result == agent_runner.ROUTER_EXHAUSTED
