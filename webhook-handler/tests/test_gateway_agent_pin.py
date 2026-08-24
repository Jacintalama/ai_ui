"""Pinning an agent, which is how a wrong pick costs one sentence.

Without a pin, a message the router misreads once it misreads every time you
rephrase it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from gateway import agent_router, pipeline
from gateway.events import MessageEvent, MessageType, SessionSource

AGENT = {"id": "agent-inbox-triage-0002", "name": "Inbox Triage",
         "base_model_id": "gpt-4o-mini",
         "meta": {"description": "You read unread email.", "toolIds": []}}
KEY = agent_router.pin_key("telegram", "42")


@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    return a


@pytest.fixture
def owui():
    client = AsyncMock()
    client.get_chat.return_value = {"title": "t", "messages": [],
                                    "history": {"messages": {}, "currentId": None}}
    client.create_chat.return_value = "chat-1"
    client.list_models.return_value = [AGENT]
    client.chat_completion.return_value = "the answer"
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok-for-user-1"}
    tasks.gateway_get_session.return_value = None
    tasks.get_state.return_value = None
    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    return MagicMock(tasks=tasks, owui=owui)


def _event(text):
    return MessageEvent(
        text=text, message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type="dm", user_id="111", user_name="Ralph"))


async def test_a_pin_phrase_saves_the_choice_and_answers_without_a_model(
        adapter, wired, owui):
    out = await pipeline.handle_event(_event("use Inbox Triage"), adapter)

    wired.tasks.set_state.assert_awaited_once()
    assert wired.tasks.set_state.await_args.args[0] == KEY
    assert "Inbox Triage" in out
    owui.chat_completion.assert_not_called()


async def test_a_pinned_agent_answers_without_asking_the_router(
        adapter, wired, owui):
    wired.tasks.get_state.return_value = {"id": AGENT["id"],
                                          "name": AGENT["name"]}

    out = await pipeline.handle_event(_event("what is new"), adapter)

    assert owui.chat_completion.await_count == 1, "the router ran anyway"
    assert owui.chat_completion.await_args.args[1] == AGENT["id"]
    assert out.rstrip().endswith("via Inbox Triage")


async def test_unpinning_clears_it(adapter, wired, owui):
    wired.tasks.get_state.return_value = {"id": AGENT["id"],
                                          "name": AGENT["name"]}

    out = await pipeline.handle_event(_event("stop using that"), adapter)

    wired.tasks.delete_state.assert_awaited_once_with(KEY)
    assert "normal" in out.lower() or "back" in out.lower()
    owui.chat_completion.assert_not_called()


async def test_a_pin_naming_a_deleted_agent_clears_itself(adapter, wired, owui):
    """The agent was deleted on the web after being pinned here."""
    wired.tasks.get_state.return_value = {"id": "agent-gone-0000",
                                          "name": "Gone"}

    out = await pipeline.handle_event(_event("what is new"), adapter)

    wired.tasks.delete_state.assert_awaited_once_with(KEY)
    assert owui.chat_completion.await_args.args[1] == settings.gateway_model
    assert "Gone" in out


async def test_a_state_failure_does_not_stop_the_answer(adapter, wired, owui):
    wired.tasks.get_state.side_effect = RuntimeError("state store down")

    out = await pipeline.handle_event(_event("what is new"), adapter)

    assert "the answer" in out
