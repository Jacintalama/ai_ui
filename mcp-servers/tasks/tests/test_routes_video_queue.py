"""Tests for POST /api/video-jobs/{job_id}/queue endpoint.

DB tests (marked skipif not _HAVE_DB) insert VideoJob rows and require a real
Postgres. They run at deploy/CI where DATABASE_URL points at aiui_test (a DB
whose name contains "test", required by the db_session fixture's safety check).
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# main's import chain (crypto_utils) requires AIUI_FERNET_KEY at import time.
# CI / the tasks container set the real key in the environment; this only fills
# in a throwaway for local offline runs so the no-DB tests can import the app.
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from main import app  # noqa: E402
from video_models import VideoJob  # noqa: E402

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB tests SKIP offline and only run at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


# ---- DB tests (skipped offline) ----


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_queue_flips_collecting_to_queued(db_session, tmp_path, monkeypatch):
    """POST /queue with >=1 screenshot flips the draft from collecting -> queued
    and returns status='queued' with a queue_position. The DB row reflects the new
    status."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    # Create a draft via POST /draft.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Queue Test", "prompt": "show the dashboard"},
            headers=HEAD,
        )
    assert r.status_code == 201
    body = r.json()
    job_id = body["id"]
    slug = body["slug"]

    # Seed a screenshot file on disk at the path _list_screenshots expects:
    # <APPS_DIR>/<slug>/.video/<jid>/screenshots/screenshot-1.png
    shots_dir = tmp_path / slug / ".video" / job_id / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    (shots_dir / "screenshot-1.png").write_bytes(b"fake-png-content")

    # POST /queue should succeed.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/queue", headers=HEAD)
    assert r.status_code == 200
    resp = r.json()
    assert resp["status"] == "queued"
    assert isinstance(resp["queue_position"], int)

    # Verify the DB row was updated.
    job = (
        await db_session.execute(
            select(VideoJob).where(VideoJob.id == uuid.UUID(job_id))
        )
    ).scalar_one()
    assert job.status == "queued"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_queue_rejects_no_screenshots_400(db_session, tmp_path, monkeypatch):
    """POST /queue on a draft with no screenshot files returns 400."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "No Shots", "prompt": "empty draft"},
            headers=HEAD,
        )
    assert r.status_code == 201
    job_id = r.json()["id"]

    # Do NOT seed any screenshot files — the directory does not exist.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/queue", headers=HEAD)
    assert r.status_code == 400


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_queue_rejects_non_draft_409(db_session, tmp_path, monkeypatch):
    """POST /queue on an already-queued job returns 409 (not a draft)."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))

    # Create and queue a draft successfully.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Double Queue", "prompt": "queue twice"},
            headers=HEAD,
        )
    assert r.status_code == 201
    body = r.json()
    job_id = body["id"]
    slug = body["slug"]

    shots_dir = tmp_path / slug / ".video" / job_id / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    (shots_dir / "screenshot-1.png").write_bytes(b"fake-png-content")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/queue", headers=HEAD)
    assert r.status_code == 200

    # Second POST /queue on the same job — status is now 'queued', not 'collecting'.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/queue", headers=HEAD)
    assert r.status_code == 409
