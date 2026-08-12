"""The one flow every platform runs.

The load-bearing assertion is that the Open WebUI client is built from the
token that resolve returned for THIS user. If the pipeline ever fell back to a
shared key, every answer would be built from the wrong person's Brain and it
would look completely correct to an admin testing it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from clients.tasks import TasksAPIError
from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource
from gateway.owui import OWUIError


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
    client.chat_completion.return_value = "the answer"
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    """Replace both network seams. Nothing in this file touches a socket."""
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok-for-user-1"}
    tasks.gateway_get_session.return_value = None

    seen_tokens = []

    def factory(token: str):
        seen_tokens.append(token)
        return owui

    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", factory)
    return MagicMock(tasks=tasks, owui=owui, tokens=seen_tokens)


def _event(text="hello", chat_type="dm", message_type=MessageType.TEXT):
    return MessageEvent(
        text=text, message_type=message_type,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type=chat_type, user_id="111",
                             user_name="Ralph"))


async def test_a_group_message_is_refused_without_calling_anything(adapter, wired):
    out = await pipeline.handle_event(_event(chat_type="group"), adapter)

    assert out == pipeline.GROUP_REFUSAL
    wired.tasks.gateway_resolve.assert_not_called()
    adapter.send_chunked.assert_awaited_once_with("42", pipeline.GROUP_REFUSAL)


async def test_an_unpaired_user_gets_a_code_and_no_model_call(adapter, wired):
    wired.tasks.gateway_resolve.return_value = {
        "linked": False, "code": "ABCD2345", "expires_at": "2026-08-10T12:00:00Z"}

    out = await pipeline.handle_event(_event(), adapter)

    assert "ABCD2345" in out
    assert "/tasks/gateway/link" in out
    wired.owui.chat_completion.assert_not_called()


async def test_the_model_is_called_with_this_users_token(adapter, wired):
    await pipeline.handle_event(_event(), adapter)
    assert wired.tokens == ["tok-for-user-1"]


async def test_the_answer_is_sent_back_chunked(adapter, wired):
    out = await pipeline.handle_event(_event(), adapter)

    assert out == "the answer"
    adapter.send_chunked.assert_awaited_once_with("42", "the answer")
    adapter.send_typing.assert_awaited_once_with("42")
    adapter.stop_typing.assert_awaited_once_with("42")


async def test_the_user_message_is_appended_to_the_completion_call(adapter, wired):
    wired.owui.get_chat.return_value = {
        "title": "t",
        "messages": [{"role": "user", "content": "earlier"},
                     {"role": "assistant", "content": "earlier answer"}],
        "history": {"messages": {}, "currentId": None}}
    wired.tasks.gateway_get_session.return_value = {
        "owui_chat_id": "chat-1", "owui_user_id": "owui-1"}

    await pipeline.handle_event(_event("what about now"), adapter)

    messages = wired.owui.chat_completion.await_args.args[0]
    assert messages[-1] == {"role": "user", "content": "what about now"}
    assert messages[0]["content"] == "earlier"


async def test_the_turn_is_written_back_to_the_open_webui_chat(adapter, wired):
    await pipeline.handle_event(_event(), adapter)

    wired.owui.update_chat.assert_awaited_once()
    _, chat = wired.owui.update_chat.await_args.args
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]


async def test_a_failed_transcript_write_still_delivers_the_answer(adapter, wired,
                                                                   caplog):
    wired.owui.update_chat.side_effect = OWUIError(500, "nope")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == "the answer"
    adapter.send_chunked.assert_awaited_once_with("42", "the answer")
    assert "transcript" in caplog.text.lower()


async def test_tasks_being_down_produces_a_sentence_not_silence(adapter, wired):
    wired.tasks.gateway_resolve.side_effect = TasksAPIError(0, "unreachable")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.TASKS_DOWN
    adapter.send_chunked.assert_awaited_once_with("42", pipeline.TASKS_DOWN)


async def test_a_model_failure_produces_a_sentence(adapter, wired):
    wired.owui.chat_completion.side_effect = OWUIError(503, "unavailable")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.MODEL_DOWN


async def test_an_unexpected_error_still_answers_the_waiting_person(adapter, wired):
    wired.owui.chat_completion.side_effect = RuntimeError("something odd")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.UNEXPECTED
    adapter.stop_typing.assert_awaited_once_with("42")


async def test_an_unhandled_message_type_says_so(adapter, wired):
    out = await pipeline.handle_event(
        _event(text="", message_type=MessageType.PHOTO), adapter)
    assert out == pipeline.UNSUPPORTED_TYPE


async def test_an_empty_text_message_is_ignored_quietly(adapter, wired):
    out = await pipeline.handle_event(_event(text="   "), adapter)
    assert out == ""
    adapter.send_chunked.assert_not_called()


def test_no_copy_constant_uses_a_dash_character():
    for name in ("GROUP_REFUSAL", "TASKS_DOWN", "MODEL_DOWN", "UNEXPECTED",
                 "UNSUPPORTED_TYPE"):
        value = getattr(pipeline, name)
        assert "—" not in value and "–" not in value, name


async def test_a_raw_transport_error_from_tasks_still_answers(adapter, wired):
    # tasks.py now wraps the whole TransportError family, but the pipeline must
    # not depend on that: anything unexpected still ends in a sentence.
    wired.tasks.gateway_resolve.side_effect = RuntimeError("connection reset")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.UNEXPECTED
    adapter.send_chunked.assert_awaited_once_with("42", pipeline.UNEXPECTED)


async def test_a_resolve_response_missing_its_token_answers(adapter, wired):
    wired.tasks.gateway_resolve.return_value = {"linked": True,
                                                "email": "u@example.com",
                                                "owui_user_id": "owui-1"}

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.UNEXPECTED


async def test_a_resolve_response_missing_its_code_answers(adapter, wired):
    wired.tasks.gateway_resolve.return_value = {"linked": False}

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.UNEXPECTED


async def test_a_failing_stop_typing_does_not_discard_the_answer(adapter, wired):
    # An exception in a finally replaces the pending return, so the caller would
    # see a failure for a message that was in fact delivered.
    adapter.stop_typing.side_effect = RuntimeError("telegram hiccup")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == "the answer"
    adapter.send_chunked.assert_awaited_once_with("42", "the answer")


async def test_a_command_is_answered_without_calling_the_model(adapter, wired):
    wired.tasks.gateway_recent_sessions.return_value = []

    out = await pipeline.handle_event(_event("/resume"), adapter)

    assert "resume" in out.lower()
    wired.owui.chat_completion.assert_not_called()
    wired.owui.create_chat.assert_not_called()


async def test_a_command_still_works_when_the_model_is_down(adapter, wired):
    # /help and /resume are how someone recovers, so they must not depend on the
    # thing that is broken.
    wired.owui.chat_completion.side_effect = OWUIError(503, "unavailable")
    wired.tasks.gateway_recent_sessions.return_value = []

    out = await pipeline.handle_event(_event("/help"), adapter)

    assert "/resume" in out


async def test_a_tasks_failure_during_a_command_says_so(adapter, wired):
    # Correct by code trace, but nothing pinned it down: someone later wrapping
    # the dispatch in a try/except that swallows would break it silently.
    wired.tasks.gateway_recent_sessions.side_effect = TasksAPIError(0, "unreachable")

    out = await pipeline.handle_event(_event("/resume"), adapter)

    assert out == pipeline.TASKS_DOWN
    adapter.send_chunked.assert_awaited_once_with("42", pipeline.TASKS_DOWN)
