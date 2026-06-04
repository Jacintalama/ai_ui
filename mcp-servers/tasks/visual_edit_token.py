"""Tasks-side verifier for visual-edit URLs. Keep in sync with
webhook-handler/handlers/visual_edit_token.py — same secret + same HMAC
payload (owner:ts:slug), same TTL.
"""
import base64
import hashlib
import hmac
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
# Long-lived link token (default 30 days): it only authorizes "open the editor
# for this slug"; ownership is re-checked and the short-lived edit capability is
# minted fresh on every load. Keep in sync with the webhook-handler signer.
EDIT_TOKEN_TTL_SECONDS = int(os.environ.get("EDIT_TOKEN_TTL_SECONDS", "2592000"))


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_edit_token(token: str, slug: str) -> str | None:
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
    expected = hmac.new(
        _SECRET, f"edit_tok:{owner}:{ts}:{slug}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        if time.time() - int(ts) > EDIT_TOKEN_TTL_SECONDS:
            return None
    except ValueError:
        return None
    return owner
