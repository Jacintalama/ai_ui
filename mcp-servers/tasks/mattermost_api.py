"""The only place the tasks service calls a Mattermost server.

Mirrors telegram_api / discord_api / slack_api: one module that ever handles a
token, one seam so no test opens a socket, and nothing logs a credential.

Unlike the others, the HOST is the user's. Mattermost is self-hosted, so every
account points at a different server, and that is the whole reason this channel
needs no approval from anybody: there is no vendor to ask. It is also why the
URL is validated here rather than trusted — it is user input that this service
is about to make a request to.
"""
import logging
import re
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

#: A hostname, optionally with a port. Deliberately narrow: anything outside
#: this is a typo, and this value becomes an outbound request.
_HOST = re.compile(r"[A-Za-z0-9._~%-]+(:\d+)?")

TIMEOUT_SECONDS = 10.0

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


class MattermostError(Exception):
    """Anything that stopped a Mattermost call from succeeding."""

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


def normalise_url(raw: str) -> str:
    """A pasted server address to a base URL, or raise.

    Refuses anything that is not http(s) with a host. This value is fetched by
    this service, so a bare scheme or a missing host would turn a typo into a
    request at something nobody meant.
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        raise MattermostError("Paste your Mattermost server URL.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    # netloc has to be checked, not merely be non-empty. "https://" survives
    # the strip above as "https:", gets a scheme prepended, and comes back with
    # a netloc of "https:" — truthy, and nonsense. A string with spaces does
    # the same. Both would become a real outbound request.
    if parsed.scheme not in ("http", "https") or not _HOST.fullmatch(parsed.netloc):
        raise MattermostError(
            "That does not look like a server address. It should look like "
            "https://mm.example.com")
    return f"{parsed.scheme}://{parsed.netloc}"


async def get_me(url: str, token: str) -> dict:
    """Proves the bot token works on that server and yields its identity."""
    base = normalise_url(url)
    try:
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{base}/api/v4/users/me",
                headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:                                   # noqa: BLE001
        # Not the repr: an httpx error carries the request, and the request
        # carries the Authorization header.
        log.warning("mattermost: users/me failed to complete")
        raise MattermostError(f"Could not reach that server: {type(exc).__name__}")

    if resp.status_code == 401:
        raise MattermostError("That server rejected the token.")
    if resp.status_code >= 400:
        raise MattermostError(
            f"That server answered {resp.status_code}. Check the URL points at "
            f"Mattermost and that bot accounts are enabled on it.")
    try:
        body = resp.json()
    except ValueError:
        raise MattermostError(
            "That address answered, but not like a Mattermost server.")
    return {"id": str(body.get("id") or ""),
            "username": body.get("username") or "",
            "url": base}
