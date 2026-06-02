"""Check connector connection status + build signed browser connect URLs."""
from urllib.parse import urlencode

import httpx

from handlers.oauth_state import sign_state

CONNECTORS = ("gmail", "drive")


def connect_url(connector: str, owner: str, *, public_base: str) -> str:
    """Signed /auth/google/start URL for the browser to open. The signed state
    binds the eventual token to `owner` (10-min TTL)."""
    state = sign_state(owner)
    return f"{public_base.rstrip('/')}/auth/google/start?{urlencode({'state': state})}"


async def is_connected(connector: str, owner: str, *, base_url: str, timeout: float = 8.0) -> bool:
    """True if `owner` has a stored token for `connector` (calls /auth/status)."""
    url = f"{base_url.rstrip('/')}/auth/status"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers={"x-user-email": owner})
        return bool(r.status_code == 200 and r.json().get("connected"))
    except Exception:
        return False
