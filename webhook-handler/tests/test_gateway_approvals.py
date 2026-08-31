"""Stopping to ask before an agent changes anything.

The turn ends and picks up on the next message, so everything here is about
that gap: reading a reply as a verdict, saying what is about to happen
clearly enough to answer, and never letting one record run twice.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import approvals, pipeline
from gateway.events import MessageEvent, MessageType, SessionSource

CALLS = [{"id": "c1", "type": "function",
          "function": {"name": "send_message",
                       "arguments": '{"to": "ralph@example.com", '
                                    '"subject": "Q3 numbers"}'}}]


# --- reading the reply -----------------------------------------------------

@pytest.mark.parametrize("text", [
    "yes", "Yes", "  YES  ", "y", "ok", "okay", "sure", "go ahead", "do it",
    "approve", "approved",
])
def test_an_approval_is_recognised(text):
    assert approvals.verdict(text) is True


@pytest.mark.parametrize("text", [
    "no", "No", "n", "stop", "cancel", "dont", "don't", "nope",
])
def test_a_refusal_is_recognised(text):
    assert approvals.verdict(text) is False


@pytest.mark.parametrize("text", [
    "what would that email say?", "yesterday I asked you something",
    "no idea what you mean", "", "   ", "nothing to do with it",
])
def test_anything_else_is_not_a_verdict(text):
    """Anything else drops the pending action and is handled as an ordinary
    message. Being trapped in a confirmation loop is the failure mode people
    hate most, so an unrecognised reply must never re-ask."""
    assert approvals.verdict(text) is None


def test_a_word_containing_no_is_not_a_refusal():
    """"nothing", "november", "not sure yet" all contain "no"."""
    assert approvals.verdict("nothing has changed") is None


# --- what the person is shown ---------------------------------------------

def test_the_prompt_names_the_tool_and_its_arguments():
    """No hand-written phrase per tool. A phrasebook covering 300+ proxy
    tools would be wrong somewhere, and where it was wrong is exactly where
    somebody approves the wrong thing."""
    out = approvals.prompt("Scout", CALLS)
    assert "Scout" in out
    assert "send_message" in out
    assert "ralph@example.com" in out
    assert "Q3 numbers" in out
    assert "yes" in out.lower() and "no" in out.lower()


def test_a_long_argument_is_truncated():
    calls = [{"id": "c1", "function": {"name": "send_message",
                                       "arguments": '{"body": "%s"}' % ("x" * 5000)}}]
    out = approvals.prompt("Scout", calls)
    assert len(out) < 1200


def test_a_malformed_call_still_produces_a_readable_question():
    """These come from a model, so the shape cannot be trusted. A crash here
    would leave somebody staring at silence."""
    for bad in ([{"id": "c1"}], [{"function": "not a dict"}],
                [{"function": {"name": None}}], ["not a dict"], []):
        out = approvals.prompt("Scout", bad)
        assert out.strip()


def test_several_writes_are_one_question():
    """Two questions back to back for one intent is worse than one."""
    calls = CALLS + [{"id": "c2", "function": {"name": "delete_draft",
                                               "arguments": "{}"}}]
    out = approvals.prompt("Scout", calls)
    assert out.count("Reply") == 1
    assert "send_message" in out and "delete_draft" in out


def test_the_key_is_per_chat():
    assert approvals.pending_key("discord", "c1") != approvals.pending_key(
        "discord", "c2")
    assert approvals.pending_key("discord", "c1").startswith("agentpending:")


# --- the flow through the pipeline ----------------------------------------

def _event(text):
    return MessageEvent(
        source=SessionSource(platform="discord", chat_id="c1",
                             user_id="u1", user_name="ralph"),
        message_type=MessageType.TEXT, text=text)


AGENT = {"id": "agent-1", "name": "Scout", "tools": ["gmail"]}
PENDING = {"agent_id": "agent-1", "agent_name": "Scout",
           "user_email": "owner@example.com", "calls": CALLS,
           "conversation": [{"role": "user", "content": "send it"}],
           "chat_id": "chat-1", "user_text": "send it"}


@pytest.fixture
def wired(monkeypatch):
    tasks = MagicMock()
    tasks.gateway_resolve = AsyncMock(return_value={
        "linked": True, "email": "owner@example.com",
        "owui_token": "tok", "owui_user_id": "u1"})
    tasks.get_state = AsyncMock(return_value=None)
    tasks.set_state = AsyncMock(return_value=True)
    tasks.delete_state = AsyncMock(return_value=True)
    tasks.agent_turn = AsyncMock(return_value={"answer": "ok", "notes": []})
    tasks.agent_turn_resume = AsyncMock(
        return_value={"answer": "Sent it.", "notes": []})
    monkeypatch.setattr(pipeline, "_tasks", tasks)

    owui = MagicMock()
    owui.chat_completion = AsyncMock(return_value="plain")
    owui.update_chat = AsyncMock()
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    monkeypatch.setattr(pipeline, "get_or_create_chat",
                        AsyncMock(return_value=("chat-1", {"messages": []})))
    monkeypatch.setattr(pipeline, "history_messages", lambda chat, n: [])
    monkeypatch.setattr(pipeline, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    adapter = MagicMock()
    adapter.send_chunked = AsyncMock()
    adapter.send_typing = AsyncMock()
    adapter.stop_typing = AsyncMock()
    return pipeline, tasks, adapter


async def test_a_pending_turn_is_stored_and_the_question_is_asked(wired):
    pl, tasks, adapter = wired
    tasks.agent_turn = AsyncMock(return_value={"pending": {
        "agent_id": "agent-1", "user_email": "owner@example.com",
        "calls": CALLS, "conversation": []}})

    sent = await pl.handle_event(_event("send that email"), adapter)

    tasks.set_state.assert_awaited_once()
    key = tasks.set_state.await_args.args[0]
    assert key == approvals.pending_key("discord", "c1")
    assert tasks.set_state.await_args.kwargs["ttl_seconds"] == approvals.PENDING_TTL_SECONDS
    assert "send_message" in sent


async def test_the_users_own_words_reach_the_agent(wired):
    """A mutant that dropped the user's message before calling agent_turn, or
    sent history alone, would pass every other test in this suite while the
    agent answers a question it was never actually asked."""
    pl, tasks, adapter = wired

    await pl.handle_event(_event("send that email"), adapter)

    messages = tasks.agent_turn.await_args.kwargs["messages"]
    assert messages[-1] == {"role": "user", "content": "send that email"}


async def test_yes_resumes_and_runs_it(wired):
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    sent = await pl.handle_event(_event("yes"), adapter)

    tasks.agent_turn_resume.assert_awaited_once()
    assert tasks.agent_turn_resume.await_args.kwargs["approved"] is True
    assert "Sent it." in sent


async def test_no_resumes_with_a_refusal(wired):
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)
    tasks.agent_turn_resume = AsyncMock(
        return_value={"answer": "Alright, I left it.", "notes": []})

    sent = await pl.handle_event(_event("no"), adapter)

    assert tasks.agent_turn_resume.await_args.kwargs["approved"] is False
    assert "Alright, I left it." in sent


async def test_the_record_is_deleted_before_it_is_acted_on(wired):
    """Otherwise a second "yes" arriving while the first is still running
    sends the same email twice."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    order = []
    tasks.delete_state = AsyncMock(side_effect=lambda k: order.append("delete"))
    tasks.agent_turn_resume = AsyncMock(
        side_effect=lambda **k: (order.append("resume"),
                                 {"answer": "done", "notes": []})[1])

    await pl.handle_event(_event("yes"), adapter)
    assert order == ["delete", "resume"]


async def test_somebody_else_cannot_approve_your_agents_write(wired):
    """The state key is per chat. In a group, or after a re-link, the person
    answering is not necessarily the person who was asked."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=dict(PENDING,
                                                  user_email="someone@else.com"))

    sent = await pl.handle_event(_event("yes"), adapter)

    tasks.agent_turn_resume.assert_not_awaited()
    assert sent == approvals.NOT_YOURS


async def test_an_unrelated_reply_drops_it_and_is_answered_normally(wired):
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    sent = await pl.handle_event(_event("actually what is the weather"), adapter)

    tasks.delete_state.assert_awaited_once()
    tasks.agent_turn_resume.assert_not_awaited()
    tasks.agent_turn.assert_awaited_once(), "the new question went unanswered"
    assert approvals.DROPPED in sent


async def test_a_pending_check_survives_a_state_store_failure(wired):
    """Reading the pin already fails open here for the same reason: a state
    outage must not make the bot stop answering."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(side_effect=RuntimeError("state down"))

    sent = await pl.handle_event(_event("hello"), adapter)
    assert sent and sent != pl.UNEXPECTED


async def test_a_pending_reply_is_checked_before_commands(wired):
    """"/help" during a pending approval must not vanish. It is not a
    verdict, so it drops the action and runs as the command it is."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    await pl.handle_event(_event("/help"), adapter)
    tasks.delete_state.assert_awaited_once()
    tasks.agent_turn_resume.assert_not_awaited()
