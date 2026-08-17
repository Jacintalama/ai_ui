"""One user's own Slack app, connected outward over Socket Mode.

Why outward. IO's own Slack app lives in exactly one workspace, so nobody
outside it could be reached at all. The obvious fix is to publish the app and
run an OAuth install flow, which means Slack's review, a public app, and
per-workspace token storage. Socket Mode skips all of it: the user creates
their own app in their own workspace, hands IO two tokens, and IO dials out.
Nothing is published, nothing is installed by us, and IO never needs a public
endpoint for it.

The two tokens are not interchangeable and fail differently:
    xoxb-   sends messages
    xapp-   opens this websocket
A wrong bot token shows up the first time IO replies. A wrong app token, or
Socket Mode left switched off, means this socket never opens and the app simply
never hears anything — which looks exactly like nobody having messaged it. That
asymmetry is why tasks proves both before storing either.

Structure follows gateway/platforms/buzz.py deliberately: one held-open socket
per user, a reconnect loop with backoff, and `connected`/`last_error` read by
the manager and reported back so the Channels page can say whether this is
actually working rather than only what was saved.
"""
import asyncio
import json
import logging
from typing import Any, Callable

import httpx
from websockets.asyncio.client import connect as ws_connect

log = logging.getLogger(__name__)

API = "https://slack.com/api"
BACKOFF_START = 2
BACKOFF_MAX = 120
TIMEOUT_SECONDS = 15.0

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


class SlackBotClient:
    """The send half, bound to one user's bot token.

    Deliberately tiny: the gateway only ever needs to post a message, and a
    full SDK client per user would be a connection pool per user on a box with
    3.8GB of RAM.
    """

    def __init__(self, bot_token: str) -> None:
        self._token = bot_token

    async def post_message(self, channel: str, text: str) -> None:
        headers = {"Authorization": f"Bearer {self._token}"}
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{API}/chat.postMessage", headers=headers,
                                     json={"channel": channel, "text": text})
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not body.get("ok"):
            # Raised, not logged and swallowed: the pipeline turns a delivery
            # failure into a sentence the person can read, and a silently
            # dropped reply is the worst outcome available.
            raise RuntimeError(f"slack refused chat.postMessage: "
                               f"{body.get('error') or resp.status_code}")


class SlackSocket:
    """One user's Socket Mode connection, held open for as long as it is on."""

    def __init__(self, bot_key: str, bot_token: str, app_token: str,
                 on_event: Callable, *, allow: Callable[[str], bool]) -> None:
        self.bot_key = bot_key
        self._app_token = app_token
        self._on_event = on_event
        self._allow = allow
        self.client = SlackBotClient(bot_token)
        self.connected = False
        self.last_error = ""
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop(),
                                             name=f"slack:{self.bot_key}")

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
                # A clean close is Slack asking us to reconnect, which is
                # routine and happens roughly hourly. Not an error, and not a
                # reason to back off.
                backoff = BACKOFF_START
            except asyncio.CancelledError:
                raise
            except Exception as e:                             # noqa: BLE001
                # Never let one user's app take down the service. The reason is
                # kept so their Channels row can show it. Never the token: a
                # Slack error can quote the request.
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                log.warning("slack[%s]: %s", self.bot_key, self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            self.connected = False

    async def _open_url(self) -> str:
        headers = {"Authorization": f"Bearer {self._app_token}"}
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{API}/apps.connections.open",
                                     headers=headers)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not body.get("ok"):
            raise RuntimeError(str(body.get("error") or "apps.connections.open failed"))
        url = body.get("url") or ""
        if not url.startswith("wss://"):
            raise RuntimeError("slack returned no socket url")
        return url

    async def _session(self) -> None:
        url = await self._open_url()
        async with ws_connect(url, open_timeout=15, close_timeout=5,
                              max_size=2 ** 20) as ws:
            async for raw in ws:
                if self._stopping:
                    return
                await self._on_frame(ws, raw)

    async def _on_frame(self, ws, raw: Any) -> None:
        try:
            frame = json.loads(raw)
        except Exception:                                      # noqa: BLE001
            return
        if not isinstance(frame, dict):
            return

        kind = frame.get("type")

        if kind == "hello":
            self.connected = True
            self.last_error = ""
            return

        if kind == "disconnect":
            # Slack cycles these connections on purpose. Raising ends the
            # session so the loop redials without treating it as a failure.
            raise ConnectionResetError(
                f"slack asked us to reconnect ({frame.get('reason') or 'no reason'})")

        if kind != "events_api":
            return

        # Acknowledge FIRST and unconditionally. Slack retries an unacked
        # envelope up to three times, so doing the work first would answer a
        # slow message three times over.
        envelope = frame.get("envelope_id")
        if envelope:
            try:
                await ws.send(json.dumps({"envelope_id": envelope}))
            except Exception:                                  # noqa: BLE001
                log.warning("slack[%s]: could not ack an envelope", self.bot_key)

        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return
        event = payload.get("event")
        if not isinstance(event, dict) or event.get("type") != "message":
            return

        user = event.get("user") or ""
        if not self._allow(str(user)):
            # Silence, not a refusal message. This is the owner's allowlist,
            # and telling an unlisted stranger that they are unlisted confirms
            # the bot is an IO bot and invites another try.
            log.info("slack[%s]: ignoring a message from an unlisted member",
                     self.bot_key)
            return

        await self._on_event(self, event)
