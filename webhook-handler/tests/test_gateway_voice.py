"""Voice memos.

A dropped voice memo is the worst failure this feature can have: the sender has
no idea whether it arrived, and re-recording is more effort than retyping. So
every voice path ends in a sentence, and the temp file is always removed.
"""
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource
from gateway.owui import OWUIError


@pytest.fixture
def adapter(tmp_path):
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    clip = tmp_path / "memo.ogg"
    clip.write_bytes(b"opus")
    a.download_media.return_value = str(clip)
    a.clip_path = str(clip)
    return a


@pytest.fixture
def owui():
    client = AsyncMock()
    client.get_chat.return_value = {"title": "t", "messages": [],
                                    "history": {"messages": {}, "currentId": None}}
    client.create_chat.return_value = "chat-1"
    client.chat_completion.return_value = "the answer"
    client.transcribe.return_value = "buy milk on the way home"
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok"}
    tasks.gateway_get_session.return_value = None
    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    return MagicMock(tasks=tasks, owui=owui)


def _voice(ref="AwACAgQ", duration=7):
    return MessageEvent(
        text="", message_type=MessageType.VOICE, media_ref=ref,
        media_duration=duration,
        source=SessionSource(platform="telegram", chat_id="42",
                             user_id="111", chat_type="dm"))


async def test_the_transcript_reaches_the_model_marked_as_speech(adapter, wired):
    await pipeline.handle_event(_voice(), adapter)

    messages = wired.owui.chat_completion.await_args.args[0]
    sent = messages[-1]["content"]
    assert "buy milk on the way home" in sent
    assert "voice message" in sent.lower()


async def test_the_temp_file_is_deleted_after_a_successful_turn(adapter, wired):
    await pipeline.handle_event(_voice(), adapter)
    assert not os.path.exists(adapter.clip_path)


async def test_the_temp_file_is_deleted_when_transcription_fails(adapter, wired):
    wired.owui.transcribe.side_effect = OWUIError(500, "whisper died")

    out = await pipeline.handle_event(_voice(), adapter)

    assert out == pipeline.TRANSCRIBE_FAILED
    assert not os.path.exists(adapter.clip_path)


async def test_a_failed_transcription_never_passes_silently(adapter, wired):
    wired.owui.transcribe.side_effect = OWUIError(500, "whisper died")
    await pipeline.handle_event(_voice(), adapter)
    wired.owui.chat_completion.assert_not_called()


async def test_a_long_clip_is_refused_before_it_is_downloaded(adapter, wired):
    out = await pipeline.handle_event(
        _voice(duration=pipeline.MAX_VOICE_SECONDS + 1), adapter)

    assert out == pipeline.CLIP_TOO_LONG
    assert "2 minute" in out
    adapter.download_media.assert_not_called()


async def test_a_clip_exactly_at_the_limit_is_accepted(adapter, wired):
    await pipeline.handle_event(
        _voice(duration=pipeline.MAX_VOICE_SECONDS), adapter)
    adapter.download_media.assert_awaited_once()


async def test_an_oversized_file_states_the_limit_too(adapter, wired):
    # The adapter's byte guard, which only fires once getFile reports a size.
    adapter.download_media.side_effect = ValueError("file too large")

    out = await pipeline.handle_event(_voice(), adapter)

    assert out == pipeline.CLIP_TOO_LONG


async def test_a_download_failure_says_so(adapter, wired):
    adapter.download_media.side_effect = RuntimeError("getFile returned no path")
    out = await pipeline.handle_event(_voice(), adapter)
    assert out == pipeline.TRANSCRIBE_FAILED


async def test_an_empty_transcript_is_reported_not_sent_as_blank(adapter, wired):
    wired.owui.transcribe.return_value = "   "
    out = await pipeline.handle_event(_voice(), adapter)
    assert out == pipeline.TRANSCRIBE_FAILED


async def test_a_voice_event_with_no_media_reference_is_reported(adapter, wired):
    out = await pipeline.handle_event(_voice(ref=None), adapter)
    assert out == pipeline.TRANSCRIBE_FAILED
    adapter.download_media.assert_not_called()


def test_the_voice_wrapper_reads_as_speech():
    wrapped = pipeline.voice_prompt("hello there")
    assert "hello there" in wrapped
    assert "—" not in wrapped and "–" not in wrapped


def test_the_voice_copy_uses_no_dash_characters():
    for name in ("TRANSCRIBE_FAILED", "CLIP_TOO_LONG"):
        value = getattr(pipeline, name)
        assert "—" not in value and "–" not in value, name
