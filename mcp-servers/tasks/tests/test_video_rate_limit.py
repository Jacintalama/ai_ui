"""Tests for the deploy-safety guards on POST /api/video-jobs/upload.

Task 5.2 (expanded): the upload route is gated by, in order,
  1. a VIDEO_ENABLED kill switch (503 when off),
  3. a free-disk guard (507 when the box is tight), and
  4. a per-user daily rate limit (429 over VIDEO_MAX_PER_USER_PER_DAY).
(Step 2 is the pre-existing auth + slug + file-count/size + role checks.)

The kill-switch and disk-guard tests run fully OFFLINE:
  * the kill switch fires before any DB/disk work, so 503 needs no database;
  * the disk guard is reachable offline because the test posts as an admin —
    `_require_role(..., is_admin=True)` returns "owner" WITHOUT a DB query, and
    SQLAlchemy's AsyncSession opens no connection until a query runs, so the
    handler reaches the disk guard (which is monkeypatched to report "full")
    before the rate-limit COUNT — the first statement that would need Postgres.

The rate-limit test issues a real COUNT query, so it is `_HAVE_DB`-skip-guarded
exactly like tests/test_routes_video_upload.py and only runs at deploy/CI.
"""
import io
import os

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from PIL import Image

# main's import chain (crypto_utils) requires AIUI_FERNET_KEY at import time.
# CI / the tasks container set the real key in the environment; this only fills
# in a throwaway for local offline runs so the no-DB tests can import the app.
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

import routes_video  # noqa: E402
from main import app  # noqa: E402
from video_models import VideoJob  # noqa: E402

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB test SKIPS offline and only runs at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (80, 80), "red").save(b, "PNG")
    return b.getvalue()


# --- Offline guards (no DB). ---


async def test_upload_disabled_returns_503(monkeypatch):
    """With VIDEO_ENABLED=false the kill switch refuses the upload (503) before
    any auth-role, disk, or DB work — even for a valid, authenticated request."""
    monkeypatch.setenv("VIDEO_ENABLED", "false")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/upload",
            data={"slug": "alpha", "prompt": "show the dashboard"},
            files=[("files", ("a.png", _png(), "image/png"))],
            headers=HEAD,
        )
    assert r.status_code == 503


async def test_upload_low_disk_returns_507(monkeypatch):
    """With the feature enabled but the disk guard reporting "full", the upload
    is rejected 507 before the rate-limit COUNT (the first DB-needing step).

    Runs offline: posting as an admin makes `_require_role` return early with no
    DB query, so the only thing standing between the request and the 507 is the
    (monkeypatched) free-disk check."""
    monkeypatch.setenv("VIDEO_ENABLED", "true")
    monkeypatch.setattr(routes_video, "enough_free_disk", lambda *a, **k: False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/upload",
            data={"slug": "alpha", "prompt": "show the dashboard"},
            files=[("files", ("a.png", _png(), "image/png"))],
            headers=HEAD,
        )
    assert r.status_code == 507


# --- DB-backed guard (needs Postgres; runs at deploy/CI). ---


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_rate_limit_returns_429(db_session, tmp_path, monkeypatch):
    """At the per-user daily cap, the next upload is rejected 429 before any
    screenshot is written. Seeds MAX jobs for the user in the last 24h, sets the
    cap to MAX, and asserts the next upload over the boundary returns 429."""
    monkeypatch.setenv("VIDEO_ENABLED", "true")
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    monkeypatch.setenv("VIDEO_MIN_FREE_DISK_MB", "0")  # isolate the rate limit
    cap = 3
    monkeypatch.setenv("VIDEO_MAX_PER_USER_PER_DAY", str(cap))
    for _ in range(cap):
        db_session.add(
            VideoJob(
                slug="alpha",
                user_email="ralph@aiui.com",
                prompt="x",
                status="queued",
            )
        )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/upload",
            data={"slug": "alpha", "prompt": "show the dashboard"},
            files=[("files", ("a.png", _png(), "image/png"))],
            headers=HEAD,
        )
    assert r.status_code == 429
