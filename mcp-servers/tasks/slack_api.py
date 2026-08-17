"""The only place the tasks service calls slack.com.

Mirrors telegram_api and discord_api: one module that ever handles a token, one
seam so no test opens a socket, and nothing logs a token.

Slack answers 200 with `ok: false` for a rejected call, so a status-code check
alone would store an invalid token and report success. Every call here reads
`ok`.

Two tokens matter for Socket Mode and they fail differently:
  xoxb-  the bot token, which sends messages
  xapp-  the app-level token, which opens the websocket
Checking only the first is what makes "saved fine, never receives anything"
possible, so `open_connection` exists to prove the second.
"""
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

API = "https://slack.com/api"
TIMEOUT_SECONDS = 10.0

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


class SlackError(Exception):
    """Anything that stopped a Slack call from succeeding."""

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


async def _call(token: str, method: str, **payload: Any) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{API}/{method}", headers=headers,
                                     json=payload or None)
    except Exception as exc:                                   # noqa: BLE001
        log.warning("slack: %s failed to complete", method)
        raise SlackError(f"Could not reach Slack: {type(exc).__name__}")

    try:
        body = resp.json()
    except ValueError:
        raise SlackError(f"Slack answered something that was not JSON "
                         f"({resp.status_code})")

    if not body.get("ok"):
        raise SlackError(str(body.get("error") or "Slack refused the call"))
    return body


async def auth_test(bot_token: str) -> dict:
    """Proves the bot token works and names the workspace it belongs to."""
    body = await _call(bot_token, "auth.test")
    return {"team": body.get("team") or "", "user": body.get("user") or "",
            "team_id": body.get("team_id") or "",
            "user_id": body.get("user_id") or ""}


async def open_connection(app_token: str) -> str:
    """Ask for a Socket Mode websocket URL, to prove the app token.

    Deliberately not connected here — this service holds no sockets. Asking is
    enough: it fails if the token is the wrong kind, if it lacks
    connections:write, or if Socket Mode was never switched on, which is the
    single most common setup mistake and is otherwise invisible until the
    moment a message does not arrive.
    """
    try:
        body = await _call(app_token, "apps.connections.open")
    except SlackError as exc:
        if exc.description in ("not_allowed_token_type", "invalid_auth"):
            raise SlackError(
                "That app-level token was refused. Check it starts with xapp-, "
                "has the connections:write scope, and that Socket Mode is "
                "switched on for the app.")
        raise
    url = body.get("url") or ""
    if not url.startswith("wss://"):
        raise SlackError("Slack did not return a Socket Mode connection.")
    return url
