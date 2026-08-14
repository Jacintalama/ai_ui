"""Buzz, which is a Nostr workspace, so IO joins it rather than being called.

Every other platform here is webhook driven: the platform calls us and the
adapter's job is to parse what arrived. Buzz has no such call. A relay is a
websocket we open and hold, authenticating as a keypair the workspace owner
minted for IO, and messages arrive on that socket.

That inverts the adapter's shape. `parse_inbound` still exists, and is still
pure, but nothing HTTP calls it: the read loop does. `send` publishes a signed
event back through the same socket instead of making a request.

One relay per user. The credentials are that user's, so two users on the same
relay still get two connections under two identities, and neither can see the
other's traffic. `buzz_manager` owns how many of these may exist at once.

What is deliberately NOT handled: encrypted direct messages (NIP-04 and
NIP-17). We subscribe to kind 1 events tagged with our pubkey, which is how an
agent is addressed in the open. An encrypted DM would arrive as a kind we do
not request and would be invisible rather than mishandled.
"""
import asyncio
import json
import logging
import time

from websockets.asyncio.client import connect as ws_connect

from gateway import nostr, schnorr
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

#: Nostr has no message size limit; relays impose their own, usually generous.
#: Chunking at a readable size beats a relay silently rejecting a long event.
BUZZ_MAX_MESSAGE = 4000

#: How long to wait for the relay to answer the subscription before assuming
#: the connection is wedged.
READY_TIMEOUT = 20.0

#: Reconnect backoff, seconds. Capped so a relay that is down overnight is
#: retried at a sane rate rather than every second for eight hours.
BACKOFF_START = 2.0
BACKOFF_MAX = 300.0

#: How far back to replay on reconnect. Without a bound, a relay that has been
#: unreachable would deliver the whole history of the workspace and IO would
#: answer messages that were handled hours ago.
REPLAY_SECONDS = 90


def sign_event(unsigned: dict, seckey: bytes) -> dict:
    """Add the signature over the event id.

    Signing the id rather than the body is what NIP-01 specifies, and it is
    only sound because the id is a hash OF the body: change any field and the
    id changes, so a signature cannot be transplanted onto different content.
    """
    return {**unsigned, "sig": schnorr.sign(bytes.fromhex(unsigned["id"]), seckey).hex()}


class BuzzAdapter(BasePlatformAdapter):
    """The send half. One per relay connection."""

    name = "buzz"
    max_message_length = BUZZ_MAX_MESSAGE

    def __init__(self, relay: "BuzzRelay") -> None:
        self._relay = relay

    async def connect(self) -> bool:
        return True          # BuzzRelay.run owns the socket's lifetime.

    async def disconnect(self) -> None:
        return None

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """A relay event to a MessageEvent, or None for anything we do not handle.

        Pure and synchronous like every other adapter's, so the read loop can
        be tested without a websocket.
        """
        if not isinstance(payload, dict):
            return None
        if payload.get("kind") != nostr.KIND_TEXT:
            return None
        author = payload.get("pubkey")
        text = payload.get("content")
        if not isinstance(author, str) or len(author) != 64:
            return None
        if not isinstance(text, str) or not text.strip():
            return None
        return MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform="buzz",
                # The person IS the conversation here: a reply is addressed to
                # their pubkey, so there is no separate room id to carry.
                chat_id=author,
                chat_type="dm",
                user_id=author,
                user_name=(payload.get("_name") or "")[:80],
            ),
            message_id=payload.get("id"),
        )

    async def send(self, chat_id: str, text: str) -> None:
        await self._relay.publish_reply(chat_id, text)


class BuzzRelay:
    """One held-open connection to one relay, as one identity.

    `on_event` is called with (MessageEvent, adapter) for anything addressed to
    us that verifies. Injected rather than imported so the read loop can be
    tested without the whole pipeline behind it.
    """

    def __init__(self, bot_key: str, relay_url: str, seckey: bytes,
                 on_event, *, allow=None) -> None:
        self.bot_key = bot_key
        self.relay_url = relay_url
        self._seckey = seckey
        self.pubkey = schnorr.pubkey_from_seckey(seckey).hex()
        self._on_event = on_event
        self._allow = allow or (lambda pubkey: True)
        self.adapter = BuzzAdapter(self)
        self._ws = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        #: Event ids already handled. A relay may redeliver on reconnect, and
        #: answering the same question twice is worse than missing it.
        self._seen: set[str] = set()
        self.last_error: str = ""
        self.connected: bool = False

    # --- lifetime ------------------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self.run(), name=f"buzz:{self.bot_key}")

    async def stop(self) -> None:
        self._stopping = True
        if self._ws is not None:
            try:
                await self._publish(nostr.presence_event(self.pubkey, "offline"))
            except Exception:                                   # noqa: BLE001
                pass                    # Courtesy only; never block a shutdown.
            try:
                await self._ws.close()
            except Exception:                                   # noqa: BLE001
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):         # noqa: BLE001
                pass
            self._task = None
        self.connected = False

    async def run(self) -> None:
        """Connect, serve, reconnect. Returns only when stopped."""
        backoff = BACKOFF_START
        while not self._stopping:
            try:
                await self._session()
                backoff = BACKOFF_START      # A clean session resets the wait.
            except asyncio.CancelledError:
                raise
            except Exception as e:                              # noqa: BLE001
                # Never let one user's bad relay take down the service. The
                # reason is kept so the Channels row can show it.
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                log.warning("buzz[%s]: %s", self.bot_key, self.last_error)
            self.connected = False
            if self._stopping:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def _session(self) -> None:
        since = int(time.time()) - REPLAY_SECONDS
        async with ws_connect(self.relay_url, open_timeout=15,
                              close_timeout=5, max_size=2 ** 20) as ws:
            self._ws = ws
            await ws.send(nostr.req_frame(
                "io", nostr.mentions_filter(self.pubkey, since=since)))
            async for raw in ws:
                if self._stopping:
                    return
                await self._on_frame(raw)
        self._ws = None

    # --- the wire ------------------------------------------------------------

    async def _on_frame(self, raw) -> None:
        try:
            frame = json.loads(raw)
        except Exception:                                       # noqa: BLE001
            return
        if not isinstance(frame, list) or not frame:
            return
        kind = frame[0]

        if kind == "AUTH" and len(frame) > 1 and isinstance(frame[1], str):
            # NIP-42. The relay names a challenge; we sign it along with the
            # relay's own url, which is what stops the answer being replayed at
            # a different relay by anyone who saw it.
            await self._send_raw(json.dumps(["AUTH", sign_event(
                nostr.auth_event(self.pubkey, self.relay_url, frame[1]),
                self._seckey)], separators=(",", ":")))
            return

        if kind == "EOSE":
            # Backlog delivered, we are live. Presence is the only status
            # signal a remote agent has, so it goes out here and not at connect
            # time, when we might still be about to be refused.
            self.connected = True
            self.last_error = ""
            await self._publish(nostr.presence_event(self.pubkey, "online"))
            return

        if kind == "NOTICE" and len(frame) > 1:
            log.info("buzz[%s]: relay said %s", self.bot_key, str(frame[1])[:200])
            return

        if kind == "OK" and len(frame) > 3 and frame[2] is False:
            # The relay refused something we published. Silent otherwise, and a
            # refused reply looks exactly like a delivered one from here.
            self.last_error = f"relay refused: {str(frame[3])[:150]}"
            log.warning("buzz[%s]: %s", self.bot_key, self.last_error)
            return

        if kind == "EVENT" and len(frame) > 2 and isinstance(frame[2], dict):
            await self._on_event_frame(frame[2])

    async def _on_event_frame(self, event: dict) -> None:
        event_id = event.get("id")
        if not isinstance(event_id, str) or event_id in self._seen:
            return
        if not self._verify(event):
            log.warning("buzz[%s]: dropped an event that did not verify",
                        self.bot_key)
            return
        if event.get("pubkey") == self.pubkey:
            return                       # Our own reply, echoed back to us.
        if not self._allow(event["pubkey"]):
            log.info("buzz[%s]: ignoring a sender who is not allowed",
                     self.bot_key)
            return

        if len(self._seen) > 2000:
            self._seen.clear()
        self._seen.add(event_id)

        parsed = self.adapter.parse_inbound(event, {})
        if parsed is not None:
            await self._on_event(parsed, self.adapter)

    def _verify(self, event: dict) -> bool:
        """Is this event really from the pubkey it claims, and unaltered?

        Relays are not trusted to have checked. Skipping this would let anyone
        who can reach the relay speak as anyone else, and the pubkey is exactly
        what the pairing decides an IO account from.
        """
        try:
            expected = nostr.event_id(event["pubkey"], event["created_at"],
                                      event["kind"], event["tags"],
                                      event["content"])
            if expected != event["id"]:
                return False
            return schnorr.verify(bytes.fromhex(event["id"]),
                                  bytes.fromhex(event["pubkey"]),
                                  bytes.fromhex(event["sig"]))
        except Exception:                                       # noqa: BLE001
            return False

    async def _send_raw(self, text: str) -> None:
        if self._ws is None:
            raise RuntimeError("not connected")
        await self._ws.send(text)

    async def _publish(self, unsigned: dict) -> None:
        await self._send_raw(nostr.event_frame(sign_event(unsigned, self._seckey)))

    async def publish_reply(self, to_pubkey: str, text: str) -> None:
        """Answer one person. Tagged so the relay routes it back to them."""
        await self._publish(nostr.unsigned_event(
            self.pubkey, nostr.KIND_TEXT, text, tags=[["p", to_pubkey]]))
