"""Signed token for the visual editor URL. HMAC-SHA256 over "<owner>:<ts>:<slug>"
with OAUTH_STATE_SECRET, so a token issued for one slug cannot be replayed
against another. Format: <b64url(owner)>.<b64url(ts)>.<b64url(sig)>.

Two identical-purpose copies live in webhook-handler (sign) and tasks (verify).
Same OAUTH_STATE_SECRET; signing payload includes the slug, so these tokens
can never be cross-substituted with the connector oauth_state tokens.
"""
import base64
import hashlib
import hmac
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
EDIT_TOKEN_TTL_SECONDS = 1800  # 30 minutes


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(owner: str, ts: str, slug: str) -> bytes:
    # `edit_tok:` domain prefix keeps these distinct from edit_cap / oauth_state
    # tokens that share OAUTH_STATE_SECRET (token-confusion guard).
    return hmac.new(_SECRET, f"edit_tok:{owner}:{ts}:{slug}".encode("utf-8"),
                    hashlib.sha256).digest()


def sign_edit_token(slug: str, owner: str) -> str:
    if not _SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET is not set")
    ts = str(int(time.time()))
    return f"{_b64(owner.encode('utf-8'))}.{_b64(ts.encode('ascii'))}.{_b64(_mac(owner, ts, slug))}"


def verify_edit_token(token: str, slug: str) -> str | None:
    """Return the owner if the signature is valid AND not expired AND bound to
    this slug, else None."""
    if not _SECRET:
        return None
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    owner_b64, ts_b64, sig_b64 = parts
    try:
        owner = _unb64(owner_b64).decode("utf-8")
        ts = _unb64(ts_b64).decode("ascii")
        sig = _unb64(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(sig, _mac(owner, ts, slug)):
        return None
    try:
        if time.time() - int(ts) > EDIT_TOKEN_TTL_SECONDS:
            return None
    except ValueError:
        return None
    return owner
