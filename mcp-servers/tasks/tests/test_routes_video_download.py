"""Tests for the video download endpoint (GET /api/video-jobs/{job_id}/download).

Download authorizes via EITHER a valid `video_dl` capability (no login needed)
OR a logged-in member. The happy path streams a real file from a real VideoJob
row, so it needs Postgres and is skipped offline. The offline tests below cover
the auth guards that fire BEFORE any DB call (bad/absent capability -> 403) and
app/route wiring, so they run locally with no database.
"""
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

# Set both secrets BEFORE importing main: AIUI_FERNET_KEY for crypto_utils, and
# OAUTH_STATE_SECRET so video_capability's module-level secret is populated the
# first time it is imported (so mint + verify in-process share one key).
os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-for-video-dl")

from main import app  # noqa: E402
from video_capability import mint_video_capability  # noqa: E402
from video_models import VideoJob, VideoJobVersion  # noqa: E402

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB test SKIPS offline and only runs at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def test_download_route_registered():
    """The download route is wired onto the app at the expected path."""
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/video-jobs/{job_id}/download" in paths


# --- Offline guards (no DB): these reject before any DB round-trip. ---


async def test_download_bad_capability_rejected():
    """A garbage capability with no admin headers is rejected with 403 before
    any DB call (the capability fails to verify and there's no login)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{uuid.uuid4()}/download?cap=not-a-real-cap")
    assert r.status_code == 403


async def test_download_requires_auth():
    """With neither a capability nor gateway identity headers, the request is
    rejected before any DB call."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{uuid.uuid4()}/download")
    assert r.status_code in (401, 403)


# --- DB happy path: needs a real Postgres, skipped offline. ---


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_download_with_valid_capability(db_session, tmp_path):
    """A valid video_dl capability bound to a finished job streams the mp4 with
    NO login headers (the no-login deep link path)."""
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-mp4-bytes")
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="show the dashboard",
            status="done",
            output_path=str(out),
        )
    )
    await db_session.commit()
    cap = mint_video_capability("ralph@aiui.com", "alpha", str(job_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}/download?cap={cap}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_download_edit_capability_rejected(db_session, tmp_path):
    """An edit capability (wrong domain) does NOT authorize a video download."""
    from edit_capability import mint_capability

    out = tmp_path / "out.mp4"
    out.write_bytes(b"fake")
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="x",
            status="done",
            output_path=str(out),
        )
    )
    await db_session.commit()
    bad = mint_capability("ralph@aiui.com", "alpha", str(job_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}/download?cap={bad}")
    assert r.status_code == 403


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_download_other_job_capability_rejected(db_session, tmp_path):
    """A valid video capability minted for a DIFFERENT job does not authorize
    this job's download (least privilege: bound to one job)."""
    out = tmp_path / "out.mp4"
    out.write_bytes(b"fake")
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="x",
            status="done",
            output_path=str(out),
        )
    )
    await db_session.commit()
    other = mint_video_capability("ralph@aiui.com", "alpha", str(uuid.uuid4()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}/download?cap={other}")
    assert r.status_code == 403


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_download_versioned_serves_that_version(db_session, tmp_path):
    """?version=N streams that version's recorded output file, not the job's
    current output_path."""
    cur = tmp_path / "out.mp4"
    cur.write_bytes(b"\x00\x00\x00\x18ftypmp42current")
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"\x00\x00\x00\x18ftypmp42v1-bytes")
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id, slug="alpha", user_email="ralph@aiui.com",
            prompt="x", status="done", output_path=str(cur),
        )
    )
    db_session.add(
        VideoJobVersion(
            id=uuid.uuid4(), job_id=job_id, version_no=1,
            plan_json={}, summary="first", output_path=str(v1),
        )
    )
    await db_session.commit()
    cap = mint_video_capability("ralph@aiui.com", "alpha", str(job_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}/download?cap={cap}&version=1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    assert r.content == b"\x00\x00\x00\x18ftypmp42v1-bytes"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_download_unknown_version_404(db_session, tmp_path):
    """?version=N for a version that does not exist is a 404."""
    cur = tmp_path / "out.mp4"
    cur.write_bytes(b"fake")
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id, slug="alpha", user_email="ralph@aiui.com",
            prompt="x", status="done", output_path=str(cur),
        )
    )
    await db_session.commit()
    cap = mint_video_capability("ralph@aiui.com", "alpha", str(job_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}/download?cap={cap}&version=7")
    assert r.status_code == 404
