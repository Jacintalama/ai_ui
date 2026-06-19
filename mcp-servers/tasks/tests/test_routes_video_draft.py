"""Tests for POST /api/video-jobs/draft, GET /api/video-jobs/current-draft,
and POST /api/video-jobs/{job_id}/draft-set endpoints.

DB tests (marked skipif not _HAVE_DB) insert VideoJob rows and require a real
Postgres. They run at deploy/CI where DATABASE_URL points at aiui_test (a DB
whose name contains "test", required by the db_session fixture's safety check).
Offline tests exercise guards that fire BEFORE any DB call and run anywhere.
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

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
async def test_create_draft_returns_201_collecting(db_session):
    """POST /draft creates a 'collecting' draft and returns id, slug, status='collecting'."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "My Draft", "prompt": "show the dashboard"},
            headers=HEAD,
        )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "collecting"
    assert body["id"]
    assert body["slug"].startswith("vid-")
    job = (
        await db_session.execute(
            select(VideoJob).where(VideoJob.id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert job.status == "collecting"
    assert job.title == "My Draft"
    assert job.user_email == "ralph@aiui.com"
    # No style/voice sent -> defaults are stored.
    assert job.style == "clean_product_demo"
    assert job.voice == "amy"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_current_draft_returns_draft_with_screenshot_count_0(db_session, tmp_path, monkeypatch):
    """GET /current-draft returns the newest collecting draft with screenshot_count 0
    when no screenshots have been uploaded yet."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Draft Title", "prompt": "some prompt"},
            headers=HEAD,
        )
    assert r.status_code == 201
    draft_id = r.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/video-jobs/current-draft", headers=HEAD)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == draft_id
    assert body["screenshot_count"] == 0
    assert body["slug"].startswith("vid-")
    assert body["title"] == "Draft Title"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_current_draft_404_when_none(db_session):
    """GET /current-draft returns 404 when there is no collecting draft for the caller."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/video-jobs/current-draft", headers=HEAD)
    assert r.status_code == 404


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_draft_set_updates_style_and_voice(db_session, tmp_path, monkeypatch):
    """POST /{job_id}/draft-set updates style+voice; current-draft reflects the change."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Test", "prompt": "do stuff"},
            headers=HEAD,
        )
    assert r.status_code == 201
    job_id = r.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/draft-set",
            json={"style": "cinematic", "voice": "ryan"},
            headers=HEAD,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["style"] == "cinematic"
    assert body["voice"] == "ryan"

    # Verify the update is visible via current-draft.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/video-jobs/current-draft", headers=HEAD)
    assert r.status_code == 200
    body = r.json()
    assert body["style"] == "cinematic"
    assert body["voice"] == "ryan"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_draft_set_rejects_non_collecting_409(db_session):
    """POST /{job_id}/draft-set returns 409 when the job status is not 'collecting'."""
    from db import session as db_session_factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Test", "prompt": "do stuff"},
            headers=HEAD,
        )
    assert r.status_code == 201
    job_id = r.json()["id"]

    # Manually flip status to 'queued' so draft-set sees a non-draft job.
    async with db_session_factory() as s:
        await s.execute(
            update(VideoJob).where(VideoJob.id == uuid.UUID(job_id)).values(status="queued")
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/draft-set",
            json={"style": "cinematic"},
            headers=HEAD,
        )
    assert r.status_code == 409


# ---- Offline tests (no DB needed) ----


async def test_create_draft_unknown_style_400():
    """An unknown style is rejected 400 before any DB call (allowlist check fires first)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Draft", "prompt": "show it", "style": "rainbow-unicorn"},
            headers=HEAD,
        )
    assert r.status_code == 400


async def test_create_draft_unknown_voice_400():
    """An unknown voice is rejected 400 before any DB call (allowlist check fires first)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Draft", "prompt": "show it", "voice": "darth-vader"},
            headers=HEAD,
        )
    assert r.status_code == 400


async def test_draft_requires_auth_401():
    """Without gateway identity headers, current_user raises 401 before the endpoint body runs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/draft",
            json={"title": "Draft", "prompt": "show it"},
        )
    assert r.status_code == 401
