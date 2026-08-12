"""The normalized inbound contract every platform adapter produces.

Modelled on hermes-agent's MessageEvent, minus the fields that only make sense
for their agent loop (auto_skill, channel_prompt, channel_context, internal).
We route to Open WebUI, which already owns the prompt and the tools.

chat_type is kept even though phase 1 is direct messages only. It is precisely
what the pipeline reads to detect and refuse a group, and the Brain is injected
into every model call, so answering in a group would print one person's private
memory to the whole room.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"


@dataclass
class SessionSource:
    """Where a message came from, in platform-neutral terms.

    chat_id is the CONVERSATION, user_id is the PERSON. On a Telegram direct
    message they happen to be the same number; do not rely on that.
    """
    platform: str                       # "telegram" | "cli"
    chat_id: str
    chat_type: str = "dm"               # anything other than "dm" is refused
    user_id: str | None = None
    user_name: str | None = None


@dataclass
class MessageEvent:
    text: str
    source: SessionSource
    message_type: MessageType = MessageType.TEXT
    # An opaque, platform-specific handle to media that has NOT been fetched
    # yet (Telegram's file_id). Parsing must stay free of network calls, so the
    # download happens later, in the pipeline.
    media_ref: str | None = None
    # Seconds, when the platform tells us up front. The pipeline refuses a long
    # clip on this, BEFORE downloading it: the duration is in the inbound
    # payload and the byte count is not known until the file is already fetched.
    media_duration: int | None = None
    message_id: str | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
