"""Tests for the admin-only screenshot upload endpoint (POST /api/video-jobs/upload).

Video generation is admins-only and per-creator: the caller supplies a title and
the slug is generated internally (vid-<job_id8>). The happy-path test needs a
real Postgres (it inserts a VideoJob row), so it is skipped offline and runs at
deploy/CI where DATABASE_URL points at a real database. The offline tests below
exercise guards that fire BEFORE any DB call (file-count 400, missing-auth 401),
so they run locally with no database.
"""
import io
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from PIL import Image
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
# var) as "no real database here" so the DB test SKIPS offline and only runs at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (80, 80), "red").save(b, "PNG")
    return b.getvalue()


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_upload_creates_queued_job(db_session, tmp_path, monkeypatch):
    """DB happy path: an admin upload stores screenshots and queues a job owned
    by its creator, with the user-typed title and an auto-generated vid- slug."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/upload",
            data={"title": "My demo", "prompt": "show the dashboard"},
            files=[("files", ("a.png", _png(), "image/png"))],
            headers=HEAD,
        )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    assert body["id"]
    job = (
        await db_session.execute(
            select(VideoJob).where(VideoJob.id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert job.title == "My demo"
    assert job.slug.startswith("vid-")
    assert job.user_email == "ralph@aiui.com"


# --- Offline guards (no DB): these fire before/around the DB calls. ---


async def test_upload_no_files_returns_400():
    """With valid auth + title but zero screenshots, the count guard rejects
    with 400 before any DB call is ever reached."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/upload",
            data={"title": "My demo", "prompt": "show the dashboard"},
            headers=HEAD,
        )
    assert r.status_code == 400


async def test_upload_no_auth_returns_401():
    """Without the gateway identity headers, current_admin raises 401 during
    dependency resolution — before the endpoint body (and any DB call) runs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/video-jobs/upload",
            data={"title": "My demo", "prompt": "show the dashboard"},
            files=[("files", ("a.png", _png(), "image/png"))],
        )
    assert r.status_code == 401
