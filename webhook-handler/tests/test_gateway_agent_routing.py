"""The pipeline sending a message to an agent instead of the default model.

The load-bearing assertions are that the id the router returns is what reaches
chat_completion, and that every way the routing can fail still answers the
person. The group refusal is re-tested here because this change sits directly
after it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource

AGENT = {"id": "agent-inbox-triage-0002", "name": "Inbox Triage",
         "base_model_id": "gpt-4o-mini",
         "meta": {"description": "You read unread email.", "toolIds": []}}


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
    # First call is the router, second is the real answer.
    client.chat_completion.side_effect = ["agent-inbox-triage-0002", "the answer"]
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


def _event(text="check my mail", chat_type="dm"):
    return MessageEvent(
        text=text, message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type=chat_type, user_id="111",
                             user_name="Ralph"))


def _answer_call(owui):
    """The chat_completion call that produced the reply, not the router one."""
    return owui.chat_completion.await_args_list[-1]


async def test_the_agent_id_is_what_answers(adapter, owui):
    await pipeline.handle_event(_event(), adapter)

    assert _answer_call(owui).args[1] == "agent-inbox-triage-0002"


async def test_the_reply_says_which_agent_answered(adapter):
    out = await pipeline.handle_event(_event(), adapter)

    assert out.rstrip().endswith("via Inbox Triage")
    assert "the answer" in out


async def test_no_agents_means_the_default_model_and_no_tag(adapter, owui):
    owui.list_models.return_value = []
    owui.chat_completion.side_effect = ["the answer"]

    out = await pipeline.handle_event(_event(), adapter)

    assert _answer_call(owui).args[1] == settings.gateway_model
    assert "via" not in out
    assert owui.chat_completion.await_count == 1, "the router ran with no candidates"


async def test_an_invented_id_falls_back_to_the_default_model(adapter, owui):
    owui.chat_completion.side_effect = ["agent-not-yours-9999", "the answer"]

    out = await pipeline.handle_event(_event(), adapter)

    assert _answer_call(owui).args[1] == settings.gateway_model
    assert "via" not in out


async def test_a_failure_to_list_models_still_answers(adapter, owui):
    owui.list_models.side_effect = RuntimeError("models endpoint down")
    owui.chat_completion.side_effect = ["the answer"]

    out = await pipeline.handle_event(_event(), adapter)

    assert "the answer" in out
    assert _answer_call(owui).args[1] == settings.gateway_model


async def test_the_transcript_records_the_agent_that_answered(adapter, owui):
    await pipeline.handle_event(_event(), adapter)

    owui.update_chat.assert_awaited()
    written = owui.update_chat.await_args.args[1]
    assert "agent-inbox-triage-0002" in str(written)


async def test_a_group_message_is_still_refused(adapter, wired, owui):
    """Regression. This change sits immediately after that check."""
    out = await pipeline.handle_event(_event(chat_type="group"), adapter)

    assert out == pipeline.GROUP_REFUSAL
    wired.tasks.gateway_resolve.assert_not_called()
    owui.list_models.assert_not_called()


async def test_a_command_never_reaches_the_router(adapter, owui):
    await pipeline.handle_event(_event(text="/help"), adapter)

    owui.list_models.assert_not_called()
    owui.chat_completion.assert_not_called()
