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

from sqlalchemy import select

from db import session
from heavy_lock import (
    build_in_flight,
    enough_free_disk,
    enough_free_ram,
    try_heavy_lock,
)
from video_models import VideoJob

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
    # Filled in Phase 3 (scripting -> voicing -> rendering -> done/failed).
    raise NotImplementedError
