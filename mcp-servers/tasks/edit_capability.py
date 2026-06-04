"""Single-task edit capability for the Visual Editor deep link.

HMAC over OAUTH_STATE_SECRET with an explicit `edit_cap:` domain prefix so it can
never be confused with visual edit tokens (`edit_tok:`) or oauth_state tokens
that share the same secret. Least privilege: a capability authorizes edit actions
on exactly one task_id for one owner, with a short TTL.

Keep the secret + format in sync with the verifier in routes_execution.py.
"""
import base64
import hashlib
import hmac
import json
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
EDIT_CAP_TTL_SECONDS = int(os.environ.get("EDIT_CAP_TTL_SECONDS", "1800"))
_DOMAIN = b"edit_cap:"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint_capability(
    owner: str, slug: str, task_id: str, ttl: int = EDIT_CAP_TTL_SECONDS
) -> str:
    """Signed `<payload>.<sig>` capability bound to one (owner, slug, task_id)."""
    if not _SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET not set")
    payload = json.dumps(
        {
            "owner": owner,
            "slug": slug,
            "task_id": str(task_id),
            "exp": int(time.time()) + ttl,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(_SECRET, _DOMAIN + payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)


def verify_capability(cap: str) -> dict | None:
    """Return {owner, slug, task_id} if `cap` is valid and unexpired, else None.

    Fails closed when the secret is unset. Constant-time signature compare."""
    if not _SECRET:
        return None
    parts = (cap or "").split(".")
    if len(parts) != 2:
        return None
    try:
        payload, sig = _unb64(parts[0]), _unb64(parts[1])
    except Exception:
        return None
    expected = hmac.new(_SECRET, _DOMAIN + payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict) or not all(
        k in data for k in ("owner", "slug", "task_id", "exp")
    ):
        return None
    try:
        if int(time.time()) >= int(data["exp"]):
            return None
    except (TypeError, ValueError):
        return None
    return {
        "owner": data["owner"],
        "slug": data["slug"],
        "task_id": str(data["task_id"]),
    }
