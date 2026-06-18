"""Tests for the video job list endpoint (GET /api/video-jobs).

The happy-path test needs a real Postgres (it inserts VideoJob rows and reads
them back), so it is skipped offline and runs at deploy/CI where DATABASE_URL
points at a real database. The offline test below exercises the auth guard that
fires BEFORE any DB call (missing-auth 401), so it runs locally with no database.
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

# main's import chain (crypto_utils) requires AIUI_FERNET_KEY at import time.
# CI / the tasks container set the real key in the environment; this only fills
# in a throwaway for local offline runs so the no-DB tests can import the app.
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from main import app  # noqa: E402
from video_models import VideoJob  # noqa: E402

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB test SKIPS offline and only runs at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL

OWNER = {"X-User-Email": "owner@x.com", "X-User-Admin": "false"}


def test_list_route_registered():
    """The bare list route is wired onto the app at the prefix path, distinct
    from the per-job status route."""
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/video-jobs" in paths
    assert "/api/video-jobs/{job_id}" in paths


# --- Offline guard (no DB): fires during dependency resolution, before any DB. ---
@pytest.mark.asyncio
async def test_list_requires_auth():
    """Without the gateway identity headers, current_user raises 401 during
    dependency resolution — before the endpoint body (and any DB call) runs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/video-jobs")
    assert r.status_code == 401


# --- DB happy path: needs a real Postgres, skipped offline. ---
@pytest.mark.asyncio
@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_list_returns_only_own_videos_newest_first(db_session):
    """A non-admin owner sees exactly their own videos, newest first, each
    carrying the list-card shape (id/title/status/created_at/current_version_no/
    output_available); another user's video is excluded."""
    from datetime import datetime, timedelta

    base = datetime(2026, 6, 1, 12, 0, 0)
    older_id = uuid.uuid4()
    newer_id = uuid.uuid4()
    other_id = uuid.uuid4()
    db_session.add_all([
        VideoJob(
            id=older_id,
            slug="alpha",
            user_email="owner@x.com",
            prompt="p",
            title="older",
            status="done",
            output_path="x",
            current_version_no=2,
            created_at=base,
        ),
        VideoJob(
            id=newer_id,
            slug="beta",
            user_email="owner@x.com",
            prompt="p",
            title="newer",
            status="queued",
            current_version_no=1,
            created_at=base + timedelta(hours=1),
        ),
        VideoJob(
            id=other_id,
            slug="gamma",
            user_email="other@x.com",
            prompt="p",
            title="theirs",
            status="queued",
            created_at=base + timedelta(hours=2),
        ),
    ])
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/video-jobs", headers=OWNER)
    assert r.status_code == 200
    videos = r.json()["videos"]

    assert [v["id"] for v in videos] == [str(newer_id), str(older_id)]
    assert other_id not in {uuid.UUID(v["id"]) for v in videos}

    newer, older = videos
    assert newer["title"] == "newer"
    assert newer["status"] == "queued"
    assert newer["current_version_no"] == 1
    assert newer["output_available"] is False
    assert newer["created_at"] is not None

    assert older["title"] == "older"
    assert older["status"] == "done"
    assert older["current_version_no"] == 2
    assert older["output_available"] is True

    expected_keys = {
        "id", "title", "status", "created_at", "current_version_no",
        "output_available",
    }
    assert set(newer.keys()) == expected_keys
