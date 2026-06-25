"""Tests for DELETE /api/video-jobs/{job_id}.

The route-registration and missing-auth (401) tests run offline (the auth guard
fires during dependency resolution, before any DB call). The owner/non-owner/
admin/404 happy paths need a real Postgres and are skipped offline (run at
deploy/CI), mirroring test_routes_video_status.py.
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from main import app  # noqa: E402
from video_models import VideoJob  # noqa: E402

ADMIN = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}
OWNER = {"X-User-Email": "owner@x.com", "X-User-Admin": "false"}
OTHER = {"X-User-Email": "other@x.com", "X-User-Admin": "false"}

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def test_delete_route_registered():
    """The job path supports the DELETE method."""
    methods = set()
    for r in app.routes:
        if getattr(r, "path", None) == "/api/video-jobs/{job_id}":
            methods |= set(getattr(r, "methods", set()) or set())
    assert "DELETE" in methods


async def test_delete_requires_auth():
    """No gateway identity headers -> 401 before any DB call."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_owner_removes_row_and_dir(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="done"))
    await db_session.commit()
    job_dir = tmp_path / "alpha" / ".video" / str(job_id)
    (job_dir / "screenshots").mkdir(parents=True)
    (job_dir / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert not job_dir.exists()
    assert await db_session.get(VideoJob, job_id) is None


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_non_owner_forbidden(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="done"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=OTHER)
    assert r.status_code == 403
    assert await db_session.get(VideoJob, job_id) is not None  # untouched


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_admin_can_delete_any(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="done"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=ADMIN)
    assert r.status_code == 200
    assert await db_session.get(VideoJob, job_id) is None


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_blocked_while_rendering(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="owner@x.com",
                            prompt="p", status="rendering"))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{job_id}", headers=OWNER)
    assert r.status_code == 409
    assert await db_session.get(VideoJob, job_id) is not None  # untouched


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_delete_unknown_job_404(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/api/video-jobs/{uuid.uuid4()}", headers=ADMIN)
    assert r.status_code == 404
