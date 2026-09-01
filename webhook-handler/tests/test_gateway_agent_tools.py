"""An agent mentioned in a channel can finally use its tools.

Until now this path caught OWUIToolCallError and answered "It can't do that
here yet". The tool loop lives in the tasks service, so the change is that an
agent message goes there instead of straight to Open WebUI.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource


def _event(text="hi scout, any mail?"):
    return MessageEvent(
        source=SessionSource(platform="discord", chat_id="c1",
                             user_id="u1", user_name="ralph"),
        message_type=MessageType.TEXT, text=text)


@pytest.fixture
def wired(monkeypatch):
    """The whole pipeline stubbed down to the one decision under test."""
    tasks = MagicMock()
    # NOTE: the real method on TasksClient is gateway_resolve, not
    # resolve_gateway_identity. See pipeline._run around line 229.
    tasks.gateway_resolve = AsyncMock(return_value={
        "linked": True, "email": "owner@example.com",
        "owui_token": "tok", "owui_user_id": "u1"})
    tasks.get_state = AsyncMock(return_value=None)
    tasks.set_state = AsyncMock(return_value=True)
    tasks.delete_state = AsyncMock(return_value=True)
    tasks.agent_turn = AsyncMock(
        return_value={"answer": "You have 4 unread.", "notes": []})
    monkeypatch.setattr(pipeline, "_tasks", tasks)

    owui = MagicMock()
    owui.chat_completion = AsyncMock(return_value="plain answer")
    owui.update_chat = AsyncMock()
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    monkeypatch.setattr(pipeline, "get_or_create_chat",
                        AsyncMock(return_value=("chat-1", {"messages": []})))
    monkeypatch.setattr(pipeline, "history_messages", lambda chat, n: [])

    adapter = MagicMock()
    adapter.send_chunked = AsyncMock()
    adapter.send_typing = AsyncMock()
    adapter.stop_typing = AsyncMock()
    return pipeline, tasks, owui, adapter


AGENT = {"id": "agent-1", "name": "Scout", "tools": ["gmail"]}


async def test_an_agent_message_goes_through_the_tool_loop(wired, monkeypatch):
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)

    tasks.agent_turn.assert_awaited_once()
    assert tasks.agent_turn.await_args.kwargs["agent_id"] == "agent-1"
    assert tasks.agent_turn.await_args.kwargs["user_email"] == "owner@example.com"
    owui.chat_completion.assert_not_awaited(), "the agent bypassed its tools"
    assert "You have 4 unread." in sent


async def test_a_plain_message_still_goes_straight_to_open_webui(wired,
                                                                monkeypatch):
    """No agent means no tools and no reason to pay for a second hop."""
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(None, None, None)))

    sent = await pl.handle_event(_event("what is the weather"), adapter)

    owui.chat_completion.assert_awaited_once()
    tasks.agent_turn.assert_not_awaited()
    assert "plain answer" in sent


async def test_the_agent_answers_in_its_own_name(wired, monkeypatch):
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert sent.startswith("Scout:")


async def test_notes_are_delivered_not_swallowed(wired, monkeypatch):
    """A refused write that nobody is told about is the worst outcome: the
    person believes it happened."""
    pl, tasks, owui, adapter = wired
    tasks.agent_turn = AsyncMock(return_value={
        "answer": "Here is the draft.",
        "notes": ["Declined to run send_email, because this agent is set to "
                  "read only."]})
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert "Declined to run send_email" in sent


async def test_a_turn_with_nothing_in_it_still_says_something(wired,
                                                              monkeypatch):
    """Nothing on this path may fail silently. See the module docstring."""
    pl, tasks, owui, adapter = wired
    tasks.agent_turn = AsyncMock(return_value={"answer": "", "notes": []})
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert sent.strip()


async def test_a_tasks_failure_is_a_sentence_not_silence(wired, monkeypatch):
    from clients.tasks import TasksAPIError

    pl, tasks, owui, adapter = wired
    tasks.agent_turn = AsyncMock(side_effect=TasksAPIError(503, "down"))
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert sent == pl.TASKS_DOWN


async def test_the_transcript_is_still_written(wired, monkeypatch):
    """The turn has to land in the user's sidebar, which is also what feeds
    the Brain."""
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    await pl.handle_event(_event(), adapter)
    owui.update_chat.assert_awaited_once()
