"""The only place the tasks service calls discord.com.

Mirrors telegram_api deliberately: one module that ever handles a bot token,
one seam (_client_factory) so no test opens a socket, and nothing here logs a
token or an exception repr that might carry one.

Discord sits behind Cloudflare, which refuses a request carrying a default
python user agent. That is not a hypothetical risk: it is exactly how the
terminal channel's client was silently broken for a day, answering 403 to a
request that was otherwise perfectly formed. So every call sends a real one.
"""
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
TIMEOUT_SECONDS = 10.0

#: Discord asks bots to identify themselves, and Cloudflare enforces it.
USER_AGENT = "AIUI-Gateway (https://ai-ui.coolestdomain.win, 1.0)"

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


class DiscordError(Exception):
    """Anything that stopped a Discord call from succeeding.

    One type for a rejection and for a timeout, so a caller has one thing to
    catch and a save can never 500 on a network blip.
    """

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


async def _call(token: str, method: str, path: str, **kw: Any) -> dict:
    headers = {
        # Bot, NOT Bearer. Bearer is for OAuth user tokens and silently 401s,
        # which would read to the user as "your token is wrong".
        "Authorization": f"Bot {token}",
        "User-Agent": USER_AGENT,
    }
    try:
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.request(method, f"{API}{path}", headers=headers, **kw)
    except Exception as exc:                                   # noqa: BLE001
        # Not logging the repr: an httpx error can carry the request, and the
        # request carries the Authorization header.
        log.warning("discord: %s %s failed to complete", method, path)
        raise DiscordError(f"Could not reach Discord: {type(exc).__name__}")

    try:
        body = resp.json()
    except ValueError:
        body = {}

    if resp.status_code >= 400:
        detail = str(body.get("message") or f"Discord refused the call ({resp.status_code})")
        raise DiscordError(detail)
    return body


async def get_me(token: str) -> dict:
    """Proves a bot token works and yields the bot's identity."""
    result = await _call(token, "GET", "/users/@me")
    return {"id": str(result.get("id") or ""),
            "username": result.get("username") or ""}
