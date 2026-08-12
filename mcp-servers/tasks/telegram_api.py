"""The only place the tasks service calls api.telegram.org.

One module so there is exactly one place that handles a bot token, and one
seam (_client_factory) so no test ever opens a socket.

NEVER log `token`. The Telegram API puts it in the URL, which is why _api()
exists and why nothing here logs a URL.
"""
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


class TelegramError(Exception):
    """Anything that stopped a Telegram call from succeeding.

    One exception type for both a rejection and a timeout, so a caller has one
    thing to catch and a save can never 500 on a network blip."""

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


async def _call(token: str, method: str, **payload: Any) -> dict:
    try:
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(_api(token, method), json=payload)
            body = resp.json()
    except Exception as exc:  # noqa: BLE001
        # Deliberately not logging the exception's repr: httpx puts the full
        # URL, and therefore the token, into its error messages.
        log.warning("telegram: %s failed to complete", method)
        raise TelegramError(f"Could not reach Telegram: {type(exc).__name__}")

    if not body.get("ok"):
        raise TelegramError(str(body.get("description") or "Telegram refused the call"))
    return body.get("result") or {}


async def get_me(token: str) -> dict:
    """Proves a token works and yields the bot's identity."""
    result = await _call(token, "getMe")
    return {"id": result.get("id"), "username": result.get("username") or ""}


async def set_webhook(token: str, url: str, secret: str) -> None:
    await _call(token, "setWebhook", url=url, secret_token=secret)


async def delete_webhook(token: str) -> None:
    await _call(token, "deleteWebhook")


async def send_message(token: str, chat_id: str, text: str) -> None:
    await _call(token, "sendMessage", chat_id=chat_id, text=text)
