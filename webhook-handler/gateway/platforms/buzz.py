"""Buzz, over plain HTTP, on a contract we define.

Buzz publishes no API, so unlike Telegram there is no platform contract to
conform to. We wrote this one and hand it to them, which means two things.

First, nothing here can lean on a platform guarantee, so every field is
checked rather than assumed. Second, the signature is the only thing standing
between this endpoint and the open internet: Caddy routes /webhook/* straight
to this service, past api-gateway's auth and its rate limiter.

Request and response rather than push, exactly like the terminal adapter, so
send() is a real no-op and the route returns handle_event's value. A buffer on
the adapter would be wrong: the registry caches one adapter per platform, so
two concurrent requests would read each other's replies.
"""
import hashlib
import hmac
import logging

from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

SIGNATURE_HEADER = "x-buzz-signature"

#: The pairing path writes a row keyed on this id and is reachable without
#: authenticating, so it is bounded here rather than at the database.
MAX_ID_LENGTH = 128

#: Long enough for anything a person types, short enough that one request
#: cannot cost an unbounded read.
MAX_TEXT_LENGTH = 8000


def sign_body(raw: bytes, secret: str) -> str:
    """The signature Buzz must send, and the one we recompute to check it.

    HMAC-SHA256 over the EXACT bytes of the request body, hex, prefixed with
    the algorithm. Over the raw bytes and not a re-serialised object, because
    two JSON encoders disagree about key order and spacing and would produce
    different signatures for the same message.
    """
    mac = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


class BuzzAdapter(BasePlatformAdapter):
    def __init__(self, secret: str = ""):
        self._secret = secret

    async def connect(self) -> bool:
        return True         # Nothing to register: Buzz calls us.

    async def disconnect(self) -> None:
        return None

    def verify_webhook_body(self, raw: bytes, headers: dict) -> bool:
        """Is this really from Buzz?

        Fails closed on an empty secret. Without that check a missing
        configuration would make every unsigned request valid, because two
        empty strings compare equal.
        """
        if not self._secret:
            log.warning("gateway: buzz has no shared secret, refusing")
            return False

        lower = {k.lower(): v for k, v in (headers or {}).items()}
        got = lower.get(SIGNATURE_HEADER)
        if not isinstance(got, str) or not got:
            return False

        return hmac.compare_digest(got, sign_body(raw, self._secret))

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """One inbound Buzz message, or None if it is not usable.

        Returns None rather than raising, so a malformed body is a 400 at the
        route instead of a traceback on a public endpoint.
        """
        payload = payload or {}

        user_id = payload.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip():
            return None
        user_id = user_id.strip()
        if len(user_id) > MAX_ID_LENGTH:
            return None

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        text = text[:MAX_TEXT_LENGTH]

        # One conversation per person by default. Without this fallback the
        # chat id would be empty and every Buzz user would share one session
        # row, which is to say one another's conversation.
        conversation = payload.get("conversation_id")
        if not isinstance(conversation, str) or not conversation.strip():
            conversation = user_id
        conversation = conversation.strip()[:MAX_ID_LENGTH]

        name = payload.get("user_name")

        return MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform="buzz",
                chat_id=conversation,
                chat_type="dm",
                user_id=user_id,
                user_name=name.strip()[:MAX_ID_LENGTH] if isinstance(name, str) else "",
            ),
        )

    async def send(self, chat_id: str, text: str) -> None:
        """No-op. The route returns the reply in its response body."""
        return None
