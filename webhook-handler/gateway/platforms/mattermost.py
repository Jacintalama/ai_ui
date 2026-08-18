"""Mattermost, as a gateway channel: one user's own server and bot.

The only channel here where the SERVER belongs to the user. Mattermost is
self-hosted, which is why it needs nobody's approval and no marketplace: there
is no vendor to ask. It also means every account points somewhere different, so
the base URL travels with the credentials rather than being a constant.

Inbound is a websocket, not a webhook, matching hermes-agent's adapter and for
the same reason: a self-hosted server usually cannot reach us, but it can
always be reached, so IO dials out.

Direct messages only, enforced on the channel type here and again by the
pipeline on chat_type. The Brain is injected into every model call, so
answering in a team channel would print one person's private memory to the
room.
"""
import asyncio
import json
import logging
from typing import Callable

import httpx
from websockets.asyncio.client import connect as ws_connect

from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

#: Mattermost's own post limit is 16383; a wall of text in a DM is unreadable
#: and blocks render better in pieces.
MATTERMOST_MAX_MESSAGE = 3000

BACKOFF_START = 2
BACKOFF_MAX = 120
TIMEOUT_SECONDS = 15.0

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


def ws_url(base: str) -> str:
    """https://mm.example.com -> wss://mm.example.com/api/v4/websocket"""
    base = (base or "").rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/api/v4/websocket"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/api/v4/websocket"
    return "wss://" + base + "/api/v4/websocket"


class MattermostClient:
    """The send half, bound to one user's server and bot token."""

    def __init__(self, base: str, token: str) -> None:
        self._base = (base or "").rstrip("/")
        self._token = token

    async def post_message(self, channel_id: str, text: str) -> None:
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{self._base}/api/v4/posts",
                headers={"Authorization": f"Bearer {self._token}"},
                json={"channel_id": channel_id, "message": text})
        if resp.status_code >= 400:
            # Raised rather than swallowed: the pipeline turns a delivery
            # failure into a sentence the person can read, and a silently
            # dropped reply is the worst outcome available.
            raise RuntimeError(f"mattermost refused the post ({resp.status_code})")


class MattermostAdapter(BasePlatformAdapter):
    name = "mattermost"
    max_message_length = MATTERMOST_MAX_MESSAGE

    def __init__(self, client: MattermostClient) -> None:
        self._client = client

    async def connect(self) -> bool:
        return self._client is not None

    async def disconnect(self) -> None:
        return None

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """A Mattermost `posted` event to a MessageEvent, or None to ignore it.

        Pure and synchronous like every adapter's, so what counts as a message
        is testable without a server. The post itself arrives as a JSON STRING
        inside the event, which is Mattermost's own shape, not a mistake.
        """
        if not isinstance(payload, dict):
            return None
        if payload.get("event") != "posted":
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        # "D" is a direct message. Anything else is a team channel or a group.
        if data.get("channel_type") != "D":
            return None

        raw = data.get("post")
        try:
            post = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:                                      # noqa: BLE001
            return None
        if not isinstance(post, dict):
            return None

        # A post the bot itself made, echoed back on its own socket. Without
        # this the bot answers itself forever.
        props = post.get("props") or {}
        if isinstance(props, dict) and props.get("from_bot") in ("true", True):
            return None
        # Edits, joins, header changes: every system post carries a type.
        if (post.get("type") or "").strip():
            return None

        text = post.get("message")
        user = post.get("user_id")
        channel = post.get("channel_id")
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
                platform="mattermost",
                # The DM channel is the conversation; the user id is the
                # person. Pairing keys on the PERSON, as everywhere else.
                chat_id=channel,
                chat_type="dm",
                user_id=user,
                user_name=str(data.get("sender_name") or "").lstrip("@")[:80],
            ),
            message_id=str(post.get("id") or "") or None,
        )

    async def send(self, chat_id: str, text: str) -> None:
        await self._client.post_message(chat_id, text)


class MattermostSocket:
    """One user's Mattermost, held open for as long as the channel is on."""

    def __init__(self, bot_key: str, base: str, token: str, on_event: Callable,
                 *, allow: Callable[[str], bool]) -> None:
        self.bot_key = bot_key
        self._base = base
        self._token = token
        self._on_event = on_event
        self._allow = allow
        self.client = MattermostClient(base, token)
        self.connected = False
        self.last_error = ""
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop(),
                                             name=f"mattermost:{self.bot_key}")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):        # noqa: BLE001
                pass
            self._task = None
        self.connected = False

    async def _loop(self) -> None:
        backoff = BACKOFF_START
        while not self._stopping:
            try:
                await self._session()
                backoff = BACKOFF_START
            except asyncio.CancelledError:
                raise
            except Exception as e:                             # noqa: BLE001
                # Never let one user's server take down the service, and never
                # record the token: a server's error can quote the request.
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                log.warning("mattermost[%s]: %s", self.bot_key, self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            self.connected = False

    async def _session(self) -> None:
        async with ws_connect(ws_url(self._base), open_timeout=15,
                              close_timeout=5, max_size=2 ** 20) as ws:
            # Mattermost authenticates AFTER the socket opens, over the socket
            # itself, rather than with a header on the upgrade request.
            await ws.send(json.dumps({
                "seq": 1, "action": "authentication_challenge",
                "data": {"token": self._token}}))
            async for raw in ws:
                if self._stopping:
                    return
                await self._on_frame(raw)

    async def _on_frame(self, raw) -> None:
        try:
            frame = json.loads(raw)
        except Exception:                                      # noqa: BLE001
            return
        if not isinstance(frame, dict):
            return

        if frame.get("event") == "hello":
            self.connected = True
            self.last_error = ""
            return

        # An authentication failure comes back as a normal reply with a status,
        # not as a refused upgrade, so a wrong token otherwise looks like a
        # socket that opened and then said nothing at all.
        if frame.get("status") == "FAIL" and frame.get("seq_reply") == 1:
            raise PermissionError("that server rejected the bot token")

        if frame.get("event") != "posted":
            return

        data = frame.get("data") or {}
        raw_post = data.get("post")
        try:
            post = json.loads(raw_post) if isinstance(raw_post, str) else raw_post
        except Exception:                                      # noqa: BLE001
            return
        user = (post or {}).get("user_id") or ""
        if not self._allow(str(user)):
            # Silence, not a refusal: telling an unlisted stranger they are
            # unlisted confirms this is an IO bot and invites another try.
            log.info("mattermost[%s]: ignoring a DM from an unlisted user",
                     self.bot_key)
            return

        await self._on_event(self, frame)
