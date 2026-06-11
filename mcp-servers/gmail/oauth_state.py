"""Signed OAuth `state` carrying the owner identity + a timestamp. HMAC-SHA256
over "<owner>:<ts>" with OAUTH_STATE_SECRET, so a forged state can't bind a
Google account to someone else's owner identity, and an old/leaked link can't
be replayed beyond the TTL. Format: <b64url(owner)>.<b64url(ts)>.<b64url(sig)>.

Three identical copies live in webhook-handler, gmail, and gdrive — the bot
signs, the connector services verify. Keep them in sync.
"""
import base64
import hashlib
import hmac
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
_TTL_SECONDS = 600  # connect link valid for 10 minutes


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_state(owner: str) -> str:
    if not _SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET is not set")
    ts = str(int(time.time()))
    sig = hmac.new(_SECRET, f"{owner}:{ts}".encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64(owner.encode('utf-8'))}.{_b64(ts.encode('ascii'))}.{_b64(sig)}"


def verify_state(state: str) -> str | None:
    """Return the owner if the signature is valid AND not expired, else None."""
    if not _SECRET:
        return None
    parts = state.split(".")
    if len(parts) != 3:
        return None
    owner_b64, ts_b64, sig_b64 = parts
    try:
        owner = _unb64(owner_b64).decode("utf-8")
        ts = _unb64(ts_b64).decode("ascii")
        sig = _unb64(sig_b64)
    except Exception:
        return None
    expected = hmac.new(_SECRET, f"{owner}:{ts}".encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        if time.time() - int(ts) > _TTL_SECONDS:
            return None
    except ValueError:
        return None
    return owner
