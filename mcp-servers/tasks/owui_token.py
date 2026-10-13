"""Mint a short-lived Open WebUI session token for one user.

Open WebUI signs its session JWTs HS256 over WEBUI_SECRET_KEY
(open_webui/utils/auth.py: SESSION_SECRET = WEBUI_SECRET_KEY, ALGORITHM =
'HS256') and get_current_user resolves the caller from the token's `id` claim.
This module can therefore present a request to Open WebUI as ANY user.

What is_valid_token accepts changed in Open WebUI 0.12.0. Up to 0.11.x it was
a revocation BLOCKLIST, so any freshly minted token with a random jti passed.
From 0.12.0 it also compares the token's `session_stamp` claim with
public.auth.session_stamp for that user and rejects the token on any
difference. The column is NULL for users that predate the upgrade and a uuid
for anyone created after it, rotated on a password change or a sign out
everywhere. A missing claim reads as None and matches a NULL column, so the
claim is copied from public.auth (session_stamp_for) when there is a value and
left out when there is not. 0.11.x has no such column and ignores the claim.
No `typ` claim: Open WebUI defaults it to 'session', which is what its own
login tokens carry.

That is why it lives here and only here. WEBUI_SECRET_KEY is set on the tasks
service alone; callers get back a token already scoped to one user with a 60
second life. Never persist a minted token and never log one, and never log a
session stamp either: with the secret it is half of a valid token.

Hand-rolled rather than added as a PyJWT dependency: the output is a plain
HS256 JWS and the same primitives already appear in edit_capability.py.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid

from sqlalchemy import text

from db import session

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 60


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _json_segment(obj: dict) -> str:
    return _b64(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode())


def mint_owui_token(user_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                    session_stamp: str | None = None) -> str:
    """Return an Open WebUI session token that resolves as `user_id`.

    `session_stamp` is that user's public.auth.session_stamp, from
    session_stamp_for. Given, it is carried as a claim; None or empty, the
    claim is left out, which is what a NULL column needs.

    Fails closed: a missing secret raises rather than returning something that
    would be silently rejected downstream and read as a model outage.
    """
    secret = os.environ.get("WEBUI_SECRET_KEY", "").encode()
    if not secret:
        raise RuntimeError("WEBUI_SECRET_KEY not set")
    if not user_id:
        raise ValueError("user_id required")
    if ttl_seconds <= 0:
        # An already-expired token would be rejected downstream and read as a
        # model outage. Cheap insurance in a module whose whole job is bounding
        # how long an impersonation token lives.
        raise ValueError("ttl_seconds must be positive")

    now = int(time.time())
    claims = {
        "id": user_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if isinstance(session_stamp, str) and session_stamp:
        claims["session_stamp"] = session_stamp
    signing_input = (
        _json_segment({"alg": ALGORITHM, "typ": "JWT"})
        + "."
        + _json_segment(claims)
    )
    sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(sig)}"


#: Postgres undefined_column. Open WebUI 0.11.x has no auth.session_stamp.
_UNDEFINED_COLUMN = "42703"
_missing_column_warned = False


def _is_missing_column(exc: BaseException) -> bool:
    """True for the undefined-column error, however SQLAlchemy wrapped it.

    sqlalchemy.exc.ProgrammingError carries the dialect's translated error
    as .orig, with .sqlstate copied from asyncpg's own error, which is its
    __cause__. Walk all of them rather than trust one layer.
    """
    seen = set()
    stack = [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if getattr(e, "sqlstate", None) == _UNDEFINED_COLUMN:
            return True
        stack.extend([getattr(e, "orig", None), e.__cause__, e.__context__])
    return False


async def session_stamp_for(user_id: str) -> str | None:
    """This user's public.auth.session_stamp, or None.

    Read fresh on every mint, no cache: mints are once per turn, each turn
    already makes its own database round trips, and a cached stamp would keep
    minting rejected tokens for the length of the cache after a password
    change rotated it.

    Fails soft to None, which mints a token without the claim: right for a
    NULL stamp and for Open WebUI 0.11.x, where the column does not exist.
    Whether the column exists is NOT remembered, because Open WebUI can be
    upgraded under a running tasks service and the next read must see it.
    Only the warning is once per process.
    """
    global _missing_column_warned
    if not user_id:
        return None
    try:
        async with session() as s:
            row = (await s.execute(
                text("SELECT session_stamp FROM public.auth WHERE id = :id"),
                {"id": user_id})).first()
    except Exception as exc:                                # noqa: BLE001
        if _is_missing_column(exc):
            if not _missing_column_warned:
                _missing_column_warned = True
                logger.warning(
                    "public.auth has no session_stamp column (Open WebUI "
                    "before 0.12.0); minting tokens without the claim")
        else:
            logger.warning("session_stamp lookup failed: %s",
                           type(exc).__name__)
        return None
    if not row:
        return None
    stamp = row[0]
    return stamp if isinstance(stamp, str) and stamp else None
