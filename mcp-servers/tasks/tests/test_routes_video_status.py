"""Tests for the video job status endpoint (GET /api/video-jobs/{job_id}).

The happy-path test needs a real Postgres (it inserts a VideoJob row and reads
it back), so it is skipped offline and runs at deploy/CI where DATABASE_URL
points at a real database. The offline tests below exercise the auth guard that
fires BEFORE any DB call (missing-auth 401) and app/route wiring, so they run
locally with no database.
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

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB test SKIPS offline and only runs at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL


def test_status_route_registered():
    """The status route is wired onto the app at the expected path."""
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/video-jobs/{job_id}" in paths


# --- Offline guard (no DB): fires during dependency resolution, before any DB. ---


async def test_status_requires_auth():
    """Without the gateway identity headers, current_admin raises 401 during
    dependency resolution — before the endpoint body (and any DB call) runs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{uuid.uuid4()}")
    assert r.status_code == 401


# --- DB happy path: needs a real Postgres, skipped offline. ---


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_status_returns_shape(db_session):
    """DB happy path: an admin gets the full status shape for a queued job,
    including the project slug and the render plan the studio scene strip reads."""
    job_id = uuid.uuid4()
    plan = {
        "template_id": "product_demo",
        "title": "t",
        "scenes": [{"caption": "intro"}],
        "narration_script": "x",
    }
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="show the dashboard",
            title="My demo",
            status="queued",
            plan_json=plan,
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}", headers=HEAD)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(job_id)
    assert body["status"] == "queued"
    assert body["queue_position"] == 0
    assert body["error"] is None
    assert body["output_available"] is False
    assert body["slug"] == "alpha"
    assert body["title"] == "My demo"
    assert body["plan"] == plan


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_status_unknown_job_404(db_session):
    """DB path: a syntactically valid but unknown job id is a 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{uuid.uuid4()}", headers=HEAD)
    assert r.status_code == 404


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_status_exposes_conversation_versions_and_pending(db_session):
    """The status payload surfaces conversation, current_version_no, and a
    `pending` flag derived from the latest un-applied proposal."""
    job_id = uuid.uuid4()
    convo = [
        {"role": "user", "kind": "message", "content": "shorten"},
        {
            "role": "assistant",
            "kind": "proposal",
            "content": "shorter",
            "plan": {
                "template_id": "product_demo",
                "title": "t",
                "scenes": [],
                "narration_script": "x",
            },
            "applied": False,
        },
    ]
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="show the dashboard",
            status="done",
            output_path="x",
            conversation=convo,
            current_version_no=3,
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}", headers=HEAD)
    assert r.status_code == 200
    body = r.json()
    assert body["current_version_no"] == 3
    assert body["pending"] is True
    assert body["conversation"] == convo
