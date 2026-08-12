"""A terminal, over plain HTTP.

Request and response rather than push, so send() is a real no-op and the route
returns handle_event's value. A buffer on the adapter would be wrong: the
registry caches one adapter per platform, so two concurrent requests would read
each other's replies.

Second platform, and the point of the exercise: if this file were long, the
adapter surface would be the wrong shape.
"""
import logging
import re

from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

#: secrets.token_hex(16). The device id IS the credential on this path, so the
#: format is checked strictly: garbage must not be able to mint pairing rows.
DEVICE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class CliAdapter(BasePlatformAdapter):
    async def connect(self) -> bool:
        return True         # Nothing to register. The route is always there.

    async def disconnect(self) -> None:
        return None

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        device_id = (payload or {}).get("device_id")
        if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.match(device_id):
            return None
        text = (payload or {}).get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        name = (payload or {}).get("device_name")
        return MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform="cli",
                # One conversation per device. A second terminal is a second
                # conversation, and /resume is how you join them.
                chat_id=device_id,
                chat_type="dm",
                user_id=device_id,
                user_name=name if isinstance(name, str) else "",
            ),
        )

    async def send(self, chat_id: str, text: str) -> None:
        """No-op. The route returns the reply in its response body."""
        return None
