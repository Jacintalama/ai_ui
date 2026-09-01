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

    async def fake_post(payload, token, timeout=None):
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

    async def fake_post(payload, token, timeout=None):
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

    async def fake_post(payload, token, timeout=None):
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
    async def fake_post(payload, token, timeout=None):
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
    async def fake_post(payload, token, timeout=None):
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


async def test_an_unrecognised_stored_mode_is_treated_as_read_only():
    """F8: routes_schedules stores tool_mode as free text, so a row can hold
    something other than exactly 'read_only', 'ask', or 'full' (a typo, or a
    value written before validation existed). The fail-closed property has
    to hold for that case too -- only exactly 'full' may unlock writes, so
    an unrecognised value like 'typo' must behave like read_only, not like
    full access. ('ask' used to be the example here; it is now a real third
    mode with its own tests above, so it no longer fits this one.)"""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="typo")

    ex.assert_not_awaited(), "an unrecognised mode must not act as full access"
    assert notes and "send_email" in notes[0]


def _malformed_calls():
    return [
        "not a dict",
        42,
        ["a", "list"],
        {"id": "x", "function": "nope"},
        {"id": "x", "function": [1, 2, 3]},
        {"id": "x", "function": {"name": {"nested": 1}}},
        {"id": "x", "function": {"name": 7}},
        {"id": "x", "function": {"name": None}},
        {"function": {"name": "send_email"}},
    ]


@pytest.mark.parametrize("bad_call", _malformed_calls())
async def test_a_malformed_tool_call_is_refused_not_fatal(bad_call):
    """F9: a tool call comes straight from a model, so its shape cannot be
    trusted. The same nine malformed shapes are already handled one layer
    down in execute_tool_call; _chat's own loop must not raise on them
    either -- it has one fewer layer of defence today, at `name =
    ((call.get("function") or {}).get("name") or "").strip()`, which raises
    AttributeError on several of these and would kill the whole run."""
    async def fake_post(payload, token, timeout=None):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[bad_call])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock(return_value="r")):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert answer == "done"


async def test_a_declined_note_reads_correctly_with_no_tool_name():
    """F10: the previous wording ("Declined to run , because...") reads as
    broken when the call carries no usable name. It must read as a
    complete sentence instead."""
    async def fake_post(payload, token, timeout=None):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[{"id": "x", "function": {"name": None}}])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert notes, notes
    assert "Declined to run ," not in notes[0]
    assert "Declined to run  " not in notes[0]
    assert notes[0].startswith("Declined to run ") and notes[0].endswith(
        "because this schedule is set to read only.")


async def test_zero_max_iterations_does_not_crash():
    """F12: max_iterations = 0 must not raise UnboundLocalError on
    `content` -- it has to be initialised before the loop that would
    otherwise be the only place it is ever assigned. Passed directly rather
    than via patch.object(agent_runner, "MAX_TOOL_ITERATIONS", 0): that
    constant is only read once, to build the parameter's default, when this
    module is imported, so patching it after the fact no longer reaches
    _chat."""
    async def fake_post(payload, token, timeout=None):
        return _reply(content="unused, the loop must never run")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="owner@example.com",
            tool_mode="read_only", max_iterations=0)

    assert answer == ""
    assert notes


async def test_a_huge_tool_result_is_shortened_before_being_resent():
    """F11: each further iteration re-posts the whole conversation, so an
    uncapped tool result is re-sent up to MAX_TOOL_ITERATIONS - 1 more
    times and can be large enough to get the request itself rejected."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("list_unread_emails")])
        return _reply(content="done")

    huge = "x" * (agent_runner.TOOL_RESULT_EXCERPT_CHARS + 5000)
    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value=huge)):
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    second = posts[1]["messages"]
    tool_msg = next(m for m in second if m.get("role") == "tool")
    assert len(tool_msg["content"]) < len(huge)
    assert len(tool_msg["content"]) < agent_runner.TOOL_RESULT_EXCERPT_CHARS + 200
    assert "shortened" in tool_msg["content"].lower()


async def test_tool_ids_reach_execute_tool_call_as_the_allowed_native_tools():
    """F6: an agent's tool_ids are not only what gets requested from Open
    WebUI -- they are also the only native tools the agent may run. _chat
    already receives tool_ids; it has to pass them through to
    execute_tool_call so the native lookup can be scoped to them."""
    async def fake_post(payload, token, timeout=None):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_tool_call("list_calendar_events")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="r")) as ex:
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["calendar"], user_email="owner@example.com",
            tool_mode="read_only")

    ex.assert_awaited_once()
    assert ex.await_args.args[2] == ["calendar"]


async def test_the_loop_stops_at_the_cap_and_says_so():
    """A model that keeps asking must not spin forever."""
    async def fake_post(payload, token, timeout=None):
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


# --- the three access modes ------------------------------------------------

async def test_a_write_under_ask_stops_and_asks_instead_of_running():
    """The whole point of "With access". Running it and then mentioning it
    would be the bug, not the feature."""
    import agent_access

    async def fake_post(payload, token, timeout=None):
        return _reply(calls=[_tool_call("send_email")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="sent")) as ex:
        with pytest.raises(agent_access.ApprovalRequired) as caught:
            await agent_runner._chat(
                token="t", model="agent-1",
                messages=[{"role": "user", "content": "send it"}],
                tool_ids=["gmail"], user_email="owner@example.com",
                tool_mode=agent_access.MODE_ASK)

    ex.assert_not_awaited(), "the write ran anyway"
    assert caught.value.calls[0]["function"]["name"] == "send_email"


async def test_reads_in_the_same_batch_still_run_before_it_asks():
    """Otherwise a turn that looks something up and then acts on it would
    throw away the lookup and have to redo it after approval."""
    import agent_access

    async def fake_post(payload, token, timeout=None):
        return _reply(calls=[_tool_call("list_unread_emails", "c1"),
                             _tool_call("send_email", "c2")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")) as ex:
        with pytest.raises(agent_access.ApprovalRequired) as caught:
            await agent_runner._chat(
                token="t", model="agent-1",
                messages=[{"role": "user", "content": "q"}],
                tool_ids=["gmail"], user_email="owner@example.com",
                tool_mode=agent_access.MODE_ASK)

    assert ex.await_count == 1, "the read should have run, the write should not"
    assert [c["id"] for c in caught.value.calls] == ["c2"]
    # The conversation handed back has to carry the read's result, or the
    # resumed turn loses it.
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1"
               for m in caught.value.conversation)


async def test_a_held_call_does_not_get_a_tool_message_of_its_own():
    """In the ask branch, `pending.append(call)` is followed by `continue`.
    Losing that `continue` would fall through and also append a refusal tool
    message for the very call the owner is being asked to approve,
    corrupting the conversation that gets handed back to resume."""
    import agent_access

    async def fake_post(payload, token, timeout=None):
        return _reply(calls=[_tool_call("list_unread_emails", "c1"),
                             _tool_call("send_email", "c2")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")):
        with pytest.raises(agent_access.ApprovalRequired) as caught:
            await agent_runner._chat(
                token="t", model="agent-1",
                messages=[{"role": "user", "content": "q"}],
                tool_ids=["gmail"], user_email="owner@example.com",
                tool_mode=agent_access.MODE_ASK)

    tool_msg_ids = [m.get("tool_call_id") for m in caught.value.conversation
                    if m.get("role") == "tool"]
    assert tool_msg_ids == ["c1"], (
        "the held write must not get a tool message of its own")


async def test_a_read_after_a_held_write_still_runs():
    """Every other multi-call test here puts the read first. A raise placed
    one level too early in the loop -- ending the batch as soon as a write
    is held, instead of finishing the whole batch first -- would still pass
    those and fail this one."""
    import agent_access

    async def fake_post(payload, token, timeout=None):
        return _reply(calls=[_tool_call("send_email", "c1"),
                             _tool_call("list_unread_emails", "c2")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")) as ex:
        with pytest.raises(agent_access.ApprovalRequired) as caught:
            await agent_runner._chat(
                token="t", model="agent-1",
                messages=[{"role": "user", "content": "q"}],
                tool_ids=["gmail"], user_email="owner@example.com",
                tool_mode=agent_access.MODE_ASK)

    ex.assert_awaited_once(), "the read after the held write should still run"
    assert [c["id"] for c in caught.value.calls] == ["c1"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c2"
               and "4 unread" in m.get("content", "")
               for m in caught.value.conversation)


async def test_a_write_under_all_access_just_runs():
    import agent_access
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="Sent.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="ok")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "send it"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode=agent_access.MODE_FULL)

    ex.assert_awaited_once()
    assert answer == "Sent."
    assert notes == []


async def test_the_refusal_says_why_in_the_callers_words():
    """The loop used to say "this schedule is set to read only" everywhere,
    which is simply false in a Discord DM."""
    import agent_access
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="I could not send that.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "send it"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode=agent_access.MODE_READ_ONLY,
            refusal_reason="this agent is set to read only")

    assert "this agent is set to read only" in notes[0]
    assert "schedule" not in notes[0]
    fed_back = posts[1]["messages"][-1]["content"]
    assert "this agent is set to read only" in fed_back


async def test_a_channel_can_be_given_a_shorter_leash():
    """A person waiting in Discord will not sit through the schedule path's
    five rounds of tool use."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply(calls=[_tool_call("list_unread_emails")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only",
            max_iterations=agent_runner.CHANNEL_MAX_TOOL_ITERATIONS)

    assert len(posts) == agent_runner.CHANNEL_MAX_TOOL_ITERATIONS
    assert "3 rounds" in notes[-1], "the note must report the real cap"


async def test_the_per_call_timeout_reaches_the_request():
    seen = {}

    async def fake_post(payload, token, timeout=None):
        seen["timeout"] = timeout
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="owner@example.com",
            tool_mode="read_only",
            timeout=agent_runner.CHANNEL_HTTP_TIMEOUT_SECONDS)

    assert seen["timeout"] == agent_runner.CHANNEL_HTTP_TIMEOUT_SECONDS
