"""Tests for the chat-refine endpoints (POST /api/video-jobs/{id}/refine, /apply).

The DB tests need a real Postgres (they insert a TaskItem for the slug-ownership
check and a VideoJob row), so they are skipped offline and run at deploy/CI where
DATABASE_URL points at a real database. The no-auth tests fire before any DB call
(current_admin raises 401 during dependency resolution), so they run locally.
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
from models import TaskItem  # noqa: E402
from video_models import VideoJob, VideoJobVersion  # noqa: E402

HEAD = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

# conftest sets a dummy DATABASE_URL ("postgresql://nobody@nowhere/nobody") via
# setdefault so no-DB modules import cleanly. Treat that sentinel (and an unset
# var) as "no real database here" so the DB tests SKIP offline and only run at
# deploy/CI where DATABASE_URL points at a real Postgres.
_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL

PLAN = {
    "template_id": "product_demo",
    "title": "t",
    "scenes": [
        {
            "screenshot": "screenshot-1.png",
            "caption": "c",
            "duration_s": 3,
            "transition": "cut",
        }
    ],
    "narration_script": "hi",
}


# --- Task 4.1: POST /{job_id}/refine ---


async def test_refine_no_auth_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{uuid.uuid4()}/refine", json={"message": "x"})
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_refine_proposal_persists_conversation(db_session, tmp_path, monkeypatch):
    import video_refine

    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    # refine_plan() raises RefineUnavailable without a key; _call_model is
    # monkeypatched below so no real API call is made.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    job_id = uuid.uuid4()
    shots = tmp_path / "alpha" / ".video" / str(job_id) / "screenshots"
    shots.mkdir(parents=True)
    (shots / "screenshot-1.png").write_bytes(b"x")
    db_session.add(
        TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name="R",
            assignee_email="ralph@aiui.com",
            description="x",
            priority="IMPORTANT",
            status="completed",
            built_app_slug="alpha",
        )
    )
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="p",
            status="done",
            plan_json=PLAN,
            output_path="x",
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        video_refine,
        "_call_model",
        lambda s, m: {"action": "propose", "message": "shorter", "plan": PLAN},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/refine",
            json={"message": "shorten"},
            headers=HEAD,
        )
    assert r.status_code == 200
    assert r.json() == {"action": "propose", "message": "shorter", "can_apply": True}
    db_session.expire_all()
    job = (
        await db_session.execute(select(VideoJob).where(VideoJob.id == job_id))
    ).scalar_one()
    convo = job.conversation or []
    assert [t.get("kind") for t in convo] == ["message", "proposal"]
    assert convo[-1]["applied"] is False
    assert convo[-1]["plan"] == PLAN


async def test_refine_503_when_disabled(monkeypatch):
    monkeypatch.setenv("VIDEO_ENABLED", "false")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{uuid.uuid4()}/refine",
                         json={"message": "x"}, headers=HEAD)
    assert r.status_code == 503


# --- Task 4.2: POST /{job_id}/apply ---


async def test_apply_no_auth_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{uuid.uuid4()}/apply")
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_apply_409_when_nothing_pending(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    db_session.add(
        TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name="R",
            assignee_email="ralph@aiui.com",
            description="x",
            priority="IMPORTANT",
            status="completed",
            built_app_slug="alpha",
        )
    )
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="p",
            status="done",
            plan_json=PLAN,
            output_path="x",
            conversation=[],
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/apply", headers=HEAD)
    assert r.status_code == 409


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_apply_queues_render(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    shots = tmp_path / "alpha" / ".video" / str(job_id) / "screenshots"
    shots.mkdir(parents=True)
    (shots / "screenshot-1.png").write_bytes(b"x")
    convo = [
        {
            "role": "assistant",
            "kind": "proposal",
            "content": "shorter",
            "plan": PLAN,
            "applied": False,
        }
    ]
    db_session.add(
        TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name="R",
            assignee_email="ralph@aiui.com",
            description="x",
            priority="IMPORTANT",
            status="completed",
            built_app_slug="alpha",
        )
    )
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="p",
            status="done",
            plan_json={},
            output_path="x",
            conversation=convo,
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/apply", headers=HEAD)
    assert r.status_code == 200
    assert r.json() == {"status": "queued"}
    db_session.expire_all()
    job = (
        await db_session.execute(select(VideoJob).where(VideoJob.id == job_id))
    ).scalar_one()
    assert job.status == "queued"
    assert job.plan_json == PLAN
    assert job.pending_summary == "shorter"
    prop = [t for t in (job.conversation or []) if t.get("kind") == "proposal"][0]
    assert prop["applied"] is True


# --- Task 4.3: POST /{job_id}/screenshots (add images mid-chat) ---


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (80, 80), "red").save(b, "PNG")
    return b.getvalue()


async def test_screenshots_no_auth_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{uuid.uuid4()}/screenshots",
            files=[("files", ("a.png", _png(), "image/png"))],
        )
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_screenshots_adds_files(db_session, tmp_path, monkeypatch):
    """A member can add a screenshot to an existing job; the returned list
    continues the screenshot-N numbering after the existing highest."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    shots = tmp_path / "alpha" / ".video" / str(job_id) / "screenshots"
    shots.mkdir(parents=True)
    (shots / "screenshot-1.png").write_bytes(_png())
    db_session.add(
        TaskItem(
            meeting_id=uuid.uuid4(),
            action_type="BUILD",
            assignee_name="R",
            assignee_email="ralph@aiui.com",
            description="x",
            priority="IMPORTANT",
            status="completed",
            built_app_slug="alpha",
        )
    )
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="p",
            status="done",
            plan_json=PLAN,
            output_path="x",
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/screenshots",
            files=[("files", ("b.png", _png(), "image/png"))],
            headers=HEAD,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["screenshots"] == ["screenshot-1.png", "screenshot-2.png"]


# --- Task 4.4: GET /{job_id}/versions + POST /{job_id}/revert ---


async def test_revert_no_auth_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{uuid.uuid4()}/revert", json={"version_no": 1}
        )
    assert r.status_code == 401


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_versions_lists_with_current_and_available(db_session, tmp_path):
    """Both version rows come back; `current` marks the job's current version
    and `available` reflects whether the version's output file exists on disk."""
    job_id = uuid.uuid4()
    v1_out = tmp_path / "v1.mp4"
    v1_out.write_bytes(b"v1")
    db_session.add(
        VideoJob(
            id=job_id,
            slug="alpha",
            user_email="ralph@aiui.com",
            prompt="p",
            status="done",
            plan_json=PLAN,
            output_path=str(v1_out),
            current_version_no=2,
        )
    )
    db_session.add(
        VideoJobVersion(
            id=uuid.uuid4(), job_id=job_id, version_no=1,
            plan_json=PLAN, summary="first", output_path=str(v1_out),
        )
    )
    db_session.add(
        VideoJobVersion(
            id=uuid.uuid4(), job_id=job_id, version_no=2,
            plan_json=PLAN, summary="second",
            output_path=str(tmp_path / "missing.mp4"),
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/video-jobs/{job_id}/versions", headers=HEAD)
    assert r.status_code == 200
    vs = r.json()["versions"]
    assert [v["version_no"] for v in vs] == [1, 2]
    assert vs[0]["available"] is True
    assert vs[1]["available"] is False
    assert vs[0]["current"] is False
    assert vs[1]["current"] is True


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_revert_to_available_version(db_session, tmp_path):
    """Reverting to a version whose file exists swaps the job to that version
    without re-rendering."""
    job_id = uuid.uuid4()
    v1_out = tmp_path / "v1.mp4"
    v1_out.write_bytes(b"v1")
    db_session.add(
        VideoJob(
            id=job_id, slug="alpha", user_email="ralph@aiui.com",
            prompt="p", status="done", plan_json={}, output_path="x",
            current_version_no=2, conversation=[],
        )
    )
    db_session.add(
        VideoJobVersion(
            id=uuid.uuid4(), job_id=job_id, version_no=1,
            plan_json=PLAN, summary="first", output_path=str(v1_out),
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/revert", json={"version_no": 1}, headers=HEAD
        )
    assert r.status_code == 200
    assert r.json() == {"status": "reverted", "output_available": True}
    db_session.expire_all()
    job = (
        await db_session.execute(select(VideoJob).where(VideoJob.id == job_id))
    ).scalar_one()
    assert job.current_version_no == 1
    assert job.output_path == str(v1_out)
    assert job.plan_json == PLAN


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_revert_to_missing_file_requeues(db_session, tmp_path):
    """Reverting to a version whose file is gone re-queues a render."""
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id, slug="alpha", user_email="ralph@aiui.com",
            prompt="p", status="done", plan_json={}, output_path="x",
            current_version_no=2, conversation=[],
        )
    )
    db_session.add(
        VideoJobVersion(
            id=uuid.uuid4(), job_id=job_id, version_no=1,
            plan_json=PLAN, summary="first",
            output_path=str(tmp_path / "gone.mp4"),
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/revert", json={"version_no": 1}, headers=HEAD
        )
    assert r.status_code == 200
    assert r.json() == {"status": "queued", "output_available": False}
    db_session.expire_all()
    job = (
        await db_session.execute(select(VideoJob).where(VideoJob.id == job_id))
    ).scalar_one()
    assert job.status == "queued"
    assert job.plan_json == PLAN


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_revert_unknown_version_404(db_session):
    """Reverting to a version that does not exist is a 404."""
    job_id = uuid.uuid4()
    db_session.add(
        VideoJob(
            id=job_id, slug="alpha", user_email="ralph@aiui.com",
            prompt="p", status="done", plan_json={}, output_path="x",
            conversation=[],
        )
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/video-jobs/{job_id}/revert", json={"version_no": 99}, headers=HEAD
        )
    assert r.status_code == 404
