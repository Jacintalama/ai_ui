"""Discord, as a gateway channel.

Discord differs from every other channel here in what it replaces: nothing. A
Discord direct message that is not a command and not an intent currently gets
no reply at all, so routing it through the gateway is purely additive. Slack
had a generic assistant answer in that position; Discord had silence.

Inbound arrives on the bot's own websocket (discord.py), not a webhook, so
`parse_inbound` is fed by the bot's on_message rather than by a route. It is
still pure and synchronous, so the decision about what counts as a message can
be tested without a Discord connection.

Direct messages only. Enforced here on the channel type and again by the
pipeline on chat_type, because the Brain is injected into every model call and
answering in a guild channel would print one person's memory to the room.
"""
import logging

from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

#: Discord's hard limit is 2000 characters for a message.
DISCORD_MAX_MESSAGE = 1900


class DiscordAdapter(BasePlatformAdapter):
    """Sends through the REST client rather than the gateway connection, so a
    reply does not depend on which shard or event loop produced the message."""

    name = "discord"
    max_message_length = DISCORD_MAX_MESSAGE

    def __init__(self, discord_client) -> None:
        self._discord = discord_client

    async def connect(self) -> bool:
        return self._discord is not None

    async def disconnect(self) -> None:
        return None

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """A normalised dict from the bot's on_message, or None to ignore.

        Takes a plain dict rather than a discord.Message so this stays testable
        without constructing library objects; the caller does that flattening,
        which is a handful of attribute reads.
        """
        if not isinstance(payload, dict):
            return None
        if payload.get("is_bot"):
            return None
        if not payload.get("is_dm"):
            return None

        text = payload.get("text")
        user = payload.get("user_id")
        if not isinstance(text, str) or not text.strip():
            return None
        if user is None:
            return None
        user = str(user)

        return MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform="discord",
                # One conversation per person. A Discord DM channel is
                # one-to-one, so the person and the conversation coincide, but
                # they are kept distinct because pairing keys on the person.
                chat_id=user,
                chat_type="dm",
                user_id=user,
                user_name=str(payload.get("user_name") or "")[:80],
            ),
            message_id=str(payload.get("message_id") or "") or None,
        )

    async def send(self, chat_id: str, text: str) -> None:
        await self._discord.send_dm(chat_id, content=text)
