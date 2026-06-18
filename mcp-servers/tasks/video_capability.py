"""Single-job video download capability for narrated MP4 deep links.

HMAC over OAUTH_STATE_SECRET with an explicit `video_dl:` domain prefix so it can
never be confused with edit capabilities (`edit_cap:`), visual edit tokens
(`edit_tok:`), or oauth_state tokens that share the same secret. Least privilege:
a capability authorizes downloading exactly one video_job_id for one owner, with
a short TTL.

Keep the secret + format in sync with the verifier in routes_video.py.
"""
import base64
import hashlib
import hmac
import json
import os
import time

_SECRET = os.environ.get("OAUTH_STATE_SECRET", "").encode()
VIDEO_DL_TTL_SECONDS = int(os.environ.get("VIDEO_DL_TTL_SECONDS", "1800"))
_DOMAIN = b"video_dl:"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint_video_capability(
    owner: str, slug: str, video_job_id: str, ttl: int = VIDEO_DL_TTL_SECONDS
) -> str:
    """Signed `<payload>.<sig>` capability bound to one (owner, slug, video_job_id)."""
    if not _SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET not set")
    payload = json.dumps(
        {
            "owner": owner,
            "slug": slug,
            "video_job_id": str(video_job_id),
            "exp": int(time.time()) + ttl,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(_SECRET, _DOMAIN + payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)


def verify_video_capability(cap: str) -> dict | None:
    """Return {owner, slug, video_job_id} if `cap` is valid and unexpired, else None.

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
        k in data for k in ("owner", "slug", "video_job_id", "exp")
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
        "video_job_id": str(data["video_job_id"]),
    }
