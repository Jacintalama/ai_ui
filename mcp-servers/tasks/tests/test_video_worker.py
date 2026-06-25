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
