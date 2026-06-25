"""Unit tests for the video worker loop skeleton.

The full stage dispatch is filled in Phase 3; here we only pin down the
kill-switch behavior of `_should_run`, which is a pure read of the
`VIDEO_ENABLED` env var (default-on).
"""
import os
import uuid

import pytest
from sqlalchemy import select

from video_models import VideoJob, VideoJobVersion
from video_worker import _should_run

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL
PLAN = {"template_id": "product_demo", "title": "t",
        "scenes": [{"screenshot": "screenshot-1.png", "caption": "c",
                    "duration_s": 3, "transition": "cut"}],
        "narration_script": "hi"}


def test_should_run_respects_kill_switch(monkeypatch):
    monkeypatch.setenv("VIDEO_ENABLED", "false")
    assert _should_run() is False
    monkeypatch.setenv("VIDEO_ENABLED", "true")
    assert _should_run() is True


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_process_job_snapshots_version(db_session, tmp_path, monkeypatch):
    import video_worker
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    monkeypatch.setattr(video_worker, "APPS_DIR", str(tmp_path))
    job_id = uuid.uuid4()
    job_dir = tmp_path / "alpha" / ".video" / str(job_id)
    job_dir.mkdir(parents=True)
    db_session.add(VideoJob(id=job_id, slug="alpha", user_email="r@x.com",
                            prompt="p", status="queued", plan_json=PLAN,
                            pending_summary="trim intro"))
    await db_session.commit()

    async def fake_render(self, slug, jid, plan):
        out = job_dir / "out.mp4"
        out.write_bytes(b"video")
        return str(out)
    monkeypatch.setattr(video_worker.VideoRenderExecutor, "render", fake_render)

    await video_worker._process_job(job_id)

    job = (await db_session.execute(select(VideoJob).where(VideoJob.id == job_id))).scalar_one()
    await db_session.refresh(job)
    assert job.status == "done"
    assert job.current_version_no == 1
    assert job.output_path.endswith("out-v1.mp4")
    assert os.path.exists(job.output_path)
    assert job.pending_summary is None
    vs = (await db_session.execute(select(VideoJobVersion).where(VideoJobVersion.job_id == job_id))).scalars().all()
    assert len(vs) == 1 and vs[0].version_no == 1 and vs[0].summary == "trim intro"


def test_build_planner_args(tmp_path, monkeypatch):
    import os, json, video_worker
    shots = tmp_path / "vid-x" / ".video" / "JID" / "screenshots"
    shots.mkdir(parents=True)
    (shots / "a.png").write_bytes(b"x"); (shots / "b.png").write_bytes(b"y")
    (tmp_path / "vid-x" / ".video" / "JID" / "site_context.json").write_text(json.dumps({"title": "T"}))
    monkeypatch.setattr(video_worker, "APPS_DIR", str(tmp_path))
    names, paths, ctx = video_worker._planner_inputs("vid-x", "JID")
    assert names == ["a.png", "b.png"]
    assert paths == [("a.png", os.path.join(str(shots), "a.png")),
                     ("b.png", os.path.join(str(shots), "b.png"))]
    assert ctx == {"title": "T"}


async def test_process_job_remotion_uses_remotion_engine(tmp_path, monkeypatch):
    """render_mode='remotion' must route to render_remotion_job, not the animated or slideshow engine."""
    import video_worker
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    job_id = uuid.uuid4()
    job_dir = tmp_path / "alpha" / ".video" / str(job_id)
    job_dir.mkdir(parents=True)
    out_mp4 = job_dir / "out.mp4"
    out_mp4.write_bytes(b"remotion-video")

    # Fake job: plan already set so scripting stage is skipped.
    fake_job = MagicMock()
    fake_job.slug = "alpha"
    fake_job.prompt = "make a remotion video"
    fake_job.plan_json = PLAN
    fake_job.pending_summary = None
    fake_job.style = "cinematic"
    fake_job.voice = None
    fake_job.render_mode = "remotion"

    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_job

    fake_s = AsyncMock()
    fake_s.execute = AsyncMock(return_value=fake_result)

    @asynccontextmanager
    async def fake_session():
        yield fake_s

    monkeypatch.setattr(video_worker, "session", fake_session)
    monkeypatch.setattr(video_worker, "APPS_DIR", str(tmp_path))
    monkeypatch.setattr(video_worker, "next_version_no", AsyncMock(return_value=1))
    monkeypatch.setattr(video_worker, "record_version", AsyncMock())

    mock_remotion = AsyncMock(return_value=str(out_mp4))
    mock_animated = AsyncMock(return_value=str(out_mp4))
    monkeypatch.setattr(video_worker, "render_remotion_job", mock_remotion)
    monkeypatch.setattr(video_worker, "render_animated_job", mock_animated)

    await video_worker._process_job(job_id)

    mock_remotion.assert_called_once()
    mock_animated.assert_not_called()
