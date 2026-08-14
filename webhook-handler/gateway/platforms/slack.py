"""Slack, as a gateway channel.

Slack already talked to IO before this existed, through the command router and
a generic assistant reply. That reply came from a shared model with a shared
system prompt: the same answer for everyone, with nobody's memory, nobody's
tools and nobody's files. This adapter is what turns a Slack DM into a message
answered by the sender's OWN IO account.

Nothing above it changes. The build-answer resume, the onboarding card and the
intent router all still get first refusal on a DM; this only takes over the
place where a generic answer used to be produced.

Direct messages only, and that is enforced twice: `parse_inbound` refuses
anything whose channel_type is not `im`, and the pipeline refuses any event
whose chat_type is not `dm`. The Brain is injected into every model call, so
answering in a channel would print one person's private memory to the room.
"""
import logging

from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

#: Slack's own limit is 40000 for a message, but a wall of text in a DM is
#: unreadable and blocks render better in pieces.
SLACK_MAX_MESSAGE = 3000


class SlackAdapter(BasePlatformAdapter):
    """Send half is the Slack Web API; the receive half is the events webhook
    that already exists, so `connect` has nothing to register."""

    name = "slack"
    max_message_length = SLACK_MAX_MESSAGE

    def __init__(self, slack_client) -> None:
        self._slack = slack_client

    async def connect(self) -> bool:
        return self._slack is not None

    async def disconnect(self) -> None:
        return None

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """A Slack `message` event to a MessageEvent, or None to ignore it.

        Pure and synchronous like every adapter's. Returning None is the normal
        way to pass on an edit, a bot echo, or a channel message.
        """
        if not isinstance(payload, dict):
            return None
        # A bot's own message, and every subtype (message_changed,
        # message_deleted, ...). Editing a panel in place fires
        # message_changed, whose text lives under event["message"], and
        # treating that as a fresh user message makes the bot answer itself.
        if payload.get("bot_id") or payload.get("subtype"):
            return None
        if payload.get("channel_type") != "im":
            return None

        text = payload.get("text")
        user = payload.get("user")
        channel = payload.get("channel")
        if not isinstance(text, str) or not text.strip():
            return None
        if not isinstance(user, str) or not user:
            return None
        if not isinstance(channel, str) or not channel:
            return None

        return MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform="slack",
                # The DM channel is the conversation; the Slack user id is the
                # person. They are different values here, unlike Telegram, and
                # pairing is keyed on the PERSON.
                chat_id=channel,
                chat_type="dm",
                user_id=user,
                user_name=payload.get("user_name") or "",
            ),
            message_id=payload.get("ts"),
        )

    async def send(self, chat_id: str, text: str) -> None:
        await self._slack.post_message(channel=chat_id, text=text)
