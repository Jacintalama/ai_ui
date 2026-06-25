"""Pipeline wiring for the video worker (`_process_job`): script -> render -> done.

OFFLINE tests (run with no Postgres, no Claude API, no SSH): the async session
is replaced with a fake async-context-manager whose ``.execute()`` returns a
result whose ``.scalar_one_or_none()`` yields a canned ``VideoJob``-like object,
and whose ``.commit()`` is a no-op. ``generate_plan`` and ``VideoRenderExecutor``
are monkeypatched so neither the model nor the build host is ever contacted.

We assert on the SQLAlchemy ``update(VideoJob)`` statements that were executed by
compiling each with the postgresql dialect and reading its bind params — that is
the public-API way to see the ``.values(...)`` the worker wrote.

One skip-guarded END-TO-END test exercises the real ``session()``/``update``
path against a live test DB (only when ``AIUI_TEST_DB=1``); it still mocks the
two heavy externals (Claude scripting + host render).
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Update
from sqlalchemy.dialects import postgresql

import video_worker


def _plan() -> dict:
    return {
        "template_id": "product_demo",
        "title": "Demo",
        "scenes": [
            {"screenshot": "screenshot-1.png", "caption": "First",
             "duration_s": 3.0, "transition": "crossfade"},
        ],
        "narration_script": "Hello there.",
        "resolution": "720p",
    }


def _fake_job(plan_json=None):
    return SimpleNamespace(
        id="job-1",
        slug="alpha",
        prompt="make me a demo",
        plan_json=plan_json,
        pending_summary=None,
        style="clean_product_demo",
        voice="amy",
        render_mode="slideshow",
        status="queued",
        error=None,
        output_path=None,
    )


def _make_session(job):
    """Build a fake async-context-manager session factory.

    Returns ``(factory, inner)`` where ``factory`` replaces ``video_worker.session``
    (each call returns the SAME context manager so every ``async with session()``
    block records its ``.execute``/``.commit`` on the one ``inner`` mock), and
    ``inner`` is the session object whose calls we assert on.
    """
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=job)

    inner = MagicMock()
    inner.execute = AsyncMock(return_value=result)
    inner.commit = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    return factory, inner


def _update_values(inner):
    """Compiled bind params for every ``update(...)`` executed on ``inner``."""
    out = []
    for call in inner.execute.await_args_list:
        stmt = call.args[0]
        if isinstance(stmt, Update):
            out.append(stmt.compile(dialect=postgresql.dialect()).params)
    return out


def _patch_heavy(monkeypatch, *, render):
    gen = AsyncMock(return_value=_plan())
    monkeypatch.setattr(video_worker, "generate_plan", gen)
    executor = MagicMock()
    executor.render = render
    monkeypatch.setattr(video_worker, "VideoRenderExecutor", MagicMock(return_value=executor))
    return gen, render


async def test_process_job_happy_path_sets_done(monkeypatch):
    job = _fake_job(plan_json=None)
    factory, inner = _make_session(job)
    monkeypatch.setattr(video_worker, "session", factory)
    gen, render = _patch_heavy(monkeypatch, render=AsyncMock(return_value="/x/out.mp4"))

    # Deterministic, offline screenshot enumeration (unsorted on disk).
    monkeypatch.setattr(video_worker.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(video_worker.os, "listdir", lambda p: ["b.png", "a.png"])

    await video_worker._process_job("job-1")

    gen.assert_awaited_once()
    # screenshots are enumerated sorted before scripting
    assert gen.await_args.args[1] == ["a.png", "b.png"]
    render.assert_awaited_once()

    updates = _update_values(inner)
    assert any(u.get("status") == "scripting" for u in updates)
    assert any(u.get("status") == "rendering" for u in updates)
    done = [u for u in updates if u.get("status") == "done"]
    assert done and done[-1].get("output_path") == "/x/out.mp4"


async def test_process_job_failure_sets_failed(monkeypatch):
    job = _fake_job(plan_json=None)
    factory, inner = _make_session(job)
    monkeypatch.setattr(video_worker, "session", factory)
    gen, render = _patch_heavy(
        monkeypatch, render=AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(video_worker.os.path, "isdir", lambda p: False)

    # Must NOT raise — the worker tick has to survive a bad job.
    await video_worker._process_job("job-1")

    updates = _update_values(inner)
    failed = [u for u in updates if u.get("status") == "failed"]
    assert failed, "expected a status='failed' update"
    assert failed[-1].get("error"), "failed update must carry a non-empty error"
    assert "boom" in failed[-1]["error"]


async def test_scripting_skipped_when_plan_exists(monkeypatch):
    job = _fake_job(plan_json=_plan())  # plan already persisted
    factory, inner = _make_session(job)
    monkeypatch.setattr(video_worker, "session", factory)
    gen, render = _patch_heavy(monkeypatch, render=AsyncMock(return_value="/x/out.mp4"))

    await video_worker._process_job("job-1")

    gen.assert_not_awaited()  # scripting skipped
    render.assert_awaited_once()  # but rendering still runs

    updates = _update_values(inner)
    assert not any(u.get("status") == "scripting" for u in updates)
    assert any(u.get("status") == "rendering" for u in updates)
    done = [u for u in updates if u.get("status") == "done"]
    assert done and done[-1].get("output_path") == "/x/out.mp4"


@pytest.mark.skipif(
    os.environ.get("AIUI_TEST_DB") != "1",
    reason="needs a live test DB (set AIUI_TEST_DB=1 + a test DATABASE_URL)",
)
async def test_process_job_end_to_end_real_db(db_session, monkeypatch):
    """Exercise the real session()/update path; heavy externals still mocked."""
    from sqlalchemy import select

    from video_models import VideoJob

    job = VideoJob(slug="alpha", user_email="t@example.com",
                   status="queued", prompt="demo")
    db_session.add(job)
    await db_session.commit()

    _patch_heavy(monkeypatch, render=AsyncMock(return_value="/x/out.mp4"))
    monkeypatch.setattr(video_worker.os.path, "isdir", lambda p: False)

    await video_worker._process_job(job.id)

    row = (await db_session.execute(
        select(VideoJob).where(VideoJob.id == job.id)
    )).scalar_one()
    assert row.status == "done"
    assert row.output_path == "/x/out.mp4"
    assert row.plan_json is not None
