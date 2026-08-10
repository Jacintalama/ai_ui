"""Mint a short-lived Open WebUI session token for one user.

Open WebUI signs its session JWTs HS256 over WEBUI_SECRET_KEY
(open_webui/utils/auth.py: SESSION_SECRET = WEBUI_SECRET_KEY, ALGORITHM =
'HS256'), get_current_user resolves the caller from the token's `id` claim,
and is_valid_token is a revocation BLOCKLIST rather than an allowlist, so a
freshly minted token with a random jti is accepted. This module can therefore
present a request to Open WebUI as ANY user.

That is why it lives here and only here. WEBUI_SECRET_KEY is set on the tasks
service alone; callers get back a token already scoped to one user with a 60
second life. Never persist a minted token and never log one.

Hand-rolled rather than added as a PyJWT dependency: the output is a plain
HS256 JWS and the same primitives already appear in edit_capability.py.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 60


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _json_segment(obj: dict) -> str:
    return _b64(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode())


def mint_owui_token(user_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Return an Open WebUI session token that resolves as `user_id`.

    Fails closed: a missing secret raises rather than returning something that
    would be silently rejected downstream and read as a model outage.
    """
    secret = os.environ.get("WEBUI_SECRET_KEY", "").encode()
    if not secret:
        raise RuntimeError("WEBUI_SECRET_KEY not set")
    if not user_id:
        raise ValueError("user_id required")

    now = int(time.time())
    signing_input = (
        _json_segment({"alg": ALGORITHM, "typ": "JWT"})
        + "."
        + _json_segment({
            "id": user_id,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl_seconds,
        })
    )
    sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(sig)}"
