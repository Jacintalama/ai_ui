"""Background video render worker: poll the queue, guard resources, render.

Polls `tasks.video_jobs` for the oldest `queued` job every 10s. Before doing
any heavy work it applies fail-safe gates so a render can never start when the
box is tight on disk/RAM or while an app build is in flight, then acquires the
shared heavy-job advisory lock (renders and builds can never run at once).

The actual stage dispatch (scripting -> voicing -> rendering -> done/failed)
is filled in Phase 3; `_process_job` is a stub here. The whole worker is
gated by a `VIDEO_ENABLED` kill switch (default-on).
"""
import asyncio
import logging
import os
import shutil

from sqlalchemy import select, update

from db import session
from heavy_lock import (
    build_in_flight,
    enough_free_disk,
    enough_free_ram,
    try_heavy_lock,
)
from video_anim import render_animated_job
from video_executor import VideoRenderExecutor
from video_models import VideoJob
from video_plan import generate_anim_plan, generate_plan
from video_versions import next_version_no, record_version

logger = logging.getLogger("video_worker")
MIN_RAM_MB = int(os.environ.get("VIDEO_MIN_FREE_RAM_MB", "1200"))
MIN_DISK_MB = int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
APPS_DIR = os.environ.get("APPS_DIR") or os.path.join(
    os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps")


def _should_run() -> bool:
    return os.environ.get("VIDEO_ENABLED", "true").strip().lower() == "true"


async def _next_queued():
    async with session() as s:
        return (await s.execute(
            select(VideoJob).where(VideoJob.status == "queued")
            .order_by(VideoJob.created_at).limit(1)
        )).scalar_one_or_none()


async def video_worker_loop() -> None:
    logger.info("video_worker_loop started")
    while True:
        try:
            if _should_run():
                await _tick_once()
        except Exception:
            logger.exception("video_worker tick failed")
        await asyncio.sleep(10)


async def _tick_once() -> None:
    job = await _next_queued()
    if job is None:
        return
    # Fail-safe gates: never start a heavy render when the box is tight or a build runs.
    if not enough_free_disk(APPS_DIR, MIN_DISK_MB) or not enough_free_ram(MIN_RAM_MB):
        return  # leave queued; try again next tick
    async with session() as s:
        if await build_in_flight(s):
            return
        async with try_heavy_lock(s) as got:
            if not got:
                return
            await _process_job(job.id)  # implemented in Phase 3


async def _process_job(job_id) -> None:
    """Run one job end-to-end: script (in-container) -> render (host) -> done.

    Stages and idempotency:
      * scripting — skipped if ``plan_json`` is already persisted (a prior tick
        may have crashed after scripting), otherwise enumerate the on-disk
        screenshots, ask the model for a plan, and persist it.
      * rendering — ``VideoRenderExecutor.render`` does the heavy host work; the
        voiceover (Piper) happens *inside* that step, so there is no separate
        worker 'voicing' stage (the enum value stays valid but unused here).
      * done — record ``output_path``.

    Any stage exception is recorded as ``status='failed'`` + ``error`` and
    swallowed (logged via ``logger.exception``) so the worker tick survives.
    """
    try:
        async with session() as s:
            job = (await s.execute(
                select(VideoJob).where(VideoJob.id == job_id)
            )).scalar_one_or_none()
            if job is None:
                return
            slug, prompt, plan, pending_summary = job.slug, job.prompt, job.plan_json, job.pending_summary
            style = job.style
            voice = job.voice
            render_mode = job.render_mode

        # Stage 1: scripting (idempotent — reuse an existing plan).
        if not plan:
            async with session() as s:
                await s.execute(
                    update(VideoJob).where(VideoJob.id == job_id)
                    .values(status="scripting")
                )
                await s.commit()
            shots_dir = os.path.join(APPS_DIR, slug, ".video", str(job_id), "screenshots")
            screenshots = sorted(os.listdir(shots_dir)) if os.path.isdir(shots_dir) else []
            plan = await (generate_anim_plan(prompt, screenshots) if render_mode == "animated"
                          else generate_plan(prompt, screenshots))
            async with session() as s:
                await s.execute(
                    update(VideoJob).where(VideoJob.id == job_id)
                    .values(plan_json=plan)
                )
                await s.commit()

        # Stage 2: rendering (the executor's host step does voice + ffmpeg).
        async with session() as s:
            await s.execute(
                update(VideoJob).where(VideoJob.id == job_id)
                .values(status="rendering")
            )
            await s.commit()
        if render_mode == "animated":
            out = await render_animated_job(APPS_DIR, slug, str(job_id), plan)
        else:
            out = await VideoRenderExecutor().render(slug, str(job_id), plan, style=style, voice=voice)

        # Stage 3: snapshot this render as a version, then mark done.
        async with session() as s:
            version_no = await next_version_no(s, job_id)
            job_dir = os.path.join(APPS_DIR, slug, ".video", str(job_id))
            versioned = os.path.join(job_dir, f"out-v{version_no}.mp4")
            try:
                shutil.copy2(out, versioned)
            except OSError:
                versioned = out  # fall back to the single out.mp4 if the copy fails
            await record_version(s, job_id, version_no, plan, pending_summary, versioned)
            await s.execute(
                update(VideoJob).where(VideoJob.id == job_id).values(
                    status="done", output_path=versioned,
                    current_version_no=version_no, pending_summary=None)
            )
            await s.commit()
    except Exception as exc:
        logger.exception("video job %s failed", job_id)
        try:
            async with session() as s:
                await s.execute(
                    update(VideoJob).where(VideoJob.id == job_id)
                    .values(status="failed", error=str(exc)[:2000])
                )
                await s.commit()
        except Exception:
            logger.exception("could not record failure for video job %s", job_id)
