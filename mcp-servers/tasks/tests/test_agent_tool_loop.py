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


async def test_an_unrecognised_stored_mode_is_treated_as_read_only():
    """F8: routes_schedules stores tool_mode as free text, so a row can hold
    something other than exactly 'read_only' or 'full' (a typo, or a value
    written before validation existed). The fail-closed property has to
    hold for that case too -- only exactly 'full' may unlock writes, so
    'ask' must behave like read_only, not like full access."""
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="ask")

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
    async def fake_post(payload, token):
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
    async def fake_post(payload, token):
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
    """F12: MAX_TOOL_ITERATIONS = 0 must not raise UnboundLocalError on
    `content` -- it has to be initialised before the loop that would
    otherwise be the only place it is ever assigned."""
    async def fake_post(payload, token):
        return _reply(content="unused, the loop must never run")

    with patch.object(agent_runner, "MAX_TOOL_ITERATIONS", 0), \
         patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="owner@example.com",
            tool_mode="read_only")

    assert answer == ""
    assert notes


async def test_a_huge_tool_result_is_shortened_before_being_resent():
    """F11: each further iteration re-posts the whole conversation, so an
    uncapped tool result is re-sent up to MAX_TOOL_ITERATIONS - 1 more
    times and can be large enough to get the request itself rejected."""
    posts = []

    async def fake_post(payload, token):
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
    async def fake_post(payload, token):
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
