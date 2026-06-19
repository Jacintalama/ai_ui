"""Tests for share_url on GET /api/video-jobs/{job_id}.

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

# main's import chain (crypto_utils) requires AIUI_FERNET_KEY at import time.
# CI / the tasks container set the real key in the environment; this only fills
# in a throwaway for local offline runs so the no-DB tests can import the app.
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from main import app  # noqa: E402
from video_models import VideoJob  # noqa: E402

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


# ---- DB tests (skipped offline) ----


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_done_job_returns_share_url(db_session, tmp_path, monkeypatch):
    """GET /{job_id} on a done job with VIDEO_PUBLIC_BASE set returns a share_url
    that starts with the configured base + /api/video-jobs/ and contains cap=."""
    monkeypatch.setenv("VIDEO_PUBLIC_BASE", "https://ai-ui.coolestdomain.win/tasks")
    monkeypatch.setenv("OAUTH_STATE_SECRET", "test-secret")

    # Create a real output file so output_path passes the None check.
    out_file = tmp_path / "out.mp4"
    out_file.write_bytes(b"fake-video")

    job_id = uuid.uuid4()
    slug = f"vid-{job_id.hex[:8]}"
    job = VideoJob(
        id=job_id,
        slug=slug,
        user_email="ralph@aiui.com",
        title="Share Test",
        prompt="test prompt",
        style="clean_product_demo",
        voice="amy",
        status="done",
        output_path=str(out_file),
    )
    db_session.add(job)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}", headers=HEAD)

    assert r.status_code == 200
    body = r.json()
    assert body["output_available"] is True
    share_url = body["share_url"]
    assert share_url is not None
    expected_prefix = f"https://ai-ui.coolestdomain.win/tasks/api/video-jobs/{job_id}/download"
    assert share_url.startswith(expected_prefix), f"share_url={share_url!r}"
    assert "cap=" in share_url


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_queued_job_returns_share_url_none(db_session, monkeypatch):
    """GET /{job_id} on a non-done (queued) job returns share_url == None."""
    monkeypatch.setenv("VIDEO_PUBLIC_BASE", "https://ai-ui.coolestdomain.win/tasks")
    monkeypatch.setenv("OAUTH_STATE_SECRET", "test-secret")

    job_id = uuid.uuid4()
    slug = f"vid-{job_id.hex[:8]}"
    job = VideoJob(
        id=job_id,
        slug=slug,
        user_email="ralph@aiui.com",
        title="Queued Test",
        prompt="test prompt",
        style="clean_product_demo",
        voice="amy",
        status="queued",
    )
    db_session.add(job)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}", headers=HEAD)

    assert r.status_code == 200
    body = r.json()
    assert body["output_available"] is False
    assert body["share_url"] is None
