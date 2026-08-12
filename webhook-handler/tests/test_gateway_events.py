"""The normalized inbound contract.

Every adapter produces one of these and the pipeline reads nothing else, so a
new platform is a parse function rather than a new branch downstream.
"""
from datetime import datetime

from gateway.events import MessageEvent, MessageType, SessionSource


def test_a_text_event_needs_only_text_and_a_source():
    event = MessageEvent(text="hello", source=SessionSource(
        platform="telegram", chat_id="42"))
    assert event.message_type is MessageType.TEXT
    assert event.media_ref is None
    assert event.media_duration is None
    assert isinstance(event.timestamp, datetime)


def test_chat_type_defaults_to_dm():
    assert SessionSource(platform="cli", chat_id="1").chat_type == "dm"


def test_the_message_types_we_actually_handle():
    assert {t.value for t in MessageType} == {"text", "voice", "photo", "document"}
