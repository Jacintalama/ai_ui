"""One user's own Discord bot, connected outward on its own gateway socket.

IO's shared Discord bot only reaches people who share a server with it, so
anyone outside Ralph's server cannot use the channel at all. A user's own bot
fixes that without anything being published: they create it in the Developer
Portal, invite it to their own server, and paste the token.

Intents are deliberately minimal, and that is a correctness decision rather
than tidiness. `message_content` is a PRIVILEGED intent: requesting it when the
user has not ticked it in the Developer Portal makes login fail outright, so
every bot whose owner missed that checkbox would simply never connect. It is
also unnecessary here — Discord always includes content for messages sent in a
DM with the bot, whatever the intent says. So we ask for DM messages and
nothing else, and the failure mode disappears.

Structure follows gateway/platforms/buzz.py: one held-open connection per user,
a reconnect loop with backoff, and `connected`/`last_error` reported back so the
Channels row can say whether this is really working.
"""
import asyncio
import logging
from typing import Callable

import discord

log = logging.getLogger(__name__)

BACKOFF_START = 2
BACKOFF_MAX = 120


class DiscordBotClient:
    """The send half, bound to one user's bot. Matches what DiscordAdapter
    expects: a `send_dm(user_id, content)`."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def send_dm(self, user_id: str, content: str) -> None:
        user = self._client.get_user(int(user_id))
        if user is None:
            # Not cached, which is the normal case for a DM-only bot that has
            # just started. Fetching is one REST call and is what makes a reply
            # possible at all after a restart.
            user = await self._client.fetch_user(int(user_id))
        await user.send(content)


class DiscordSocket:
    """One user's bot, online for as long as the channel is switched on."""

    def __init__(self, bot_key: str, token: str, on_event: Callable, *,
                 allow: Callable[[str], bool]) -> None:
        self.bot_key = bot_key
        self._token = token
        self._on_event = on_event
        self._allow = allow
        self.connected = False
        self.last_error = ""
        self._task: asyncio.Task | None = None
        self._client: discord.Client | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop(),
                                             name=f"discord:{self.bot_key}")

    async def stop(self) -> None:
        self._stopping = True
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:                                  # noqa: BLE001
                pass
            self._client = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):        # noqa: BLE001
                pass
            self._task = None
        self.connected = False

    def _build_client(self) -> discord.Client:
        intents = discord.Intents.none()
        intents.dm_messages = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():                                  # noqa: ANN202
            self.connected = True
            self.last_error = ""
            log.info("discord[%s]: connected", self.bot_key)

        @client.event
        async def on_message(message):                         # noqa: ANN202
            if message.author.bot:
                return
            if not _is_dm(message):
                # Guild channels are never touched. The Brain is injected into
                # every model call, so answering in a channel would print one
                # person's private memory to the room.
                return
            if not self._allow(str(message.author.id)):
                # Silence rather than a refusal: telling an unlisted stranger
                # they are unlisted confirms this is an IO bot and invites
                # another attempt.
                log.info("discord[%s]: ignoring a DM from an unlisted user",
                         self.bot_key)
                return
            await self._on_event(self, message)

        return client

    async def _loop(self) -> None:
        backoff = BACKOFF_START
        while not self._stopping:
            client = self._build_client()
            self._client = client
            self.client = DiscordBotClient(client)
            try:
                await client.start(self._token)
                backoff = BACKOFF_START
            except asyncio.CancelledError:
                raise
            except discord.LoginFailure as e:
                # The token is wrong or was reset. Retrying cannot fix it, and
                # hammering Discord with a dead token is how an application
                # gets rate limited, so stop and let the row show why.
                self.last_error = f"Discord refused the token: {e}"[:200]
                log.warning("discord[%s]: %s", self.bot_key, self.last_error)
                self.connected = False
                return
            except Exception as e:                             # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                log.warning("discord[%s]: %s", self.bot_key, self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            finally:
                self.connected = False
                try:
                    if not client.is_closed():
                        await client.close()
                except Exception:                              # noqa: BLE001
                    pass


def _is_dm(message) -> bool:
    """True for a direct message to the bot.

    `guild is None` rather than comparing `channel.type` against
    discord.ChannelType.private, on purpose. Several test modules here stub
    sys.modules["discord"] so that main can be imported without the audio
    dependencies, and a stub has no ChannelType — which made this module pass
    its own tests and blow up in the full suite. Reading an attribute off the
    message needs no enum, so it works under a stub and cannot break if the
    library reorganises its enums.
    """
    return getattr(message, "guild", None) is None


def flatten(message) -> dict:
    """A discord.Message reduced to what DiscordAdapter.parse_inbound reads.

    Kept next to the socket rather than inside the adapter so the adapter stays
    testable without constructing library objects, which is the reason it takes
    a plain dict in the first place.
    """
    return {
        "is_bot": bool(message.author.bot),
        "is_dm": _is_dm(message),
        "text": message.content or "",
        "user_id": message.author.id,
        "user_name": getattr(message.author, "display_name", "") or "",
        "message_id": message.id,
    }
