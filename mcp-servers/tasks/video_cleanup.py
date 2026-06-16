"""Retention cleanup for the video generator (tasks schema).

Two best-effort, crash-proof jobs run once an hour:

  1. **Prune render inputs.** Once a job is ``done`` and its ``out.mp4`` exists
     on disk, the intermediate inputs (screenshots, the Piper voice files, the
     caption PNGs, the narration text) are dead weight — delete them, keep only
     the finished ``out.mp4``.
  2. **Expire old jobs.** When a job's ``created_at`` is older than
     ``VIDEO_RETENTION_DAYS`` (default 7), delete the whole
     ``apps/<slug>/.video/<job_id>/`` directory *and* the ``video_jobs`` row.

``expired()`` (pure) and ``prune_inputs()`` (pure filesystem) are unit-tested
offline. The DB sweep (``_sweep_once`` / ``video_cleanup_loop``) mirrors the
scheduler's ``_tick_once`` / ``schedule_tick_loop``; it needs a live Postgres
connection so it is covered by live e2e, not unit-tested locally.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("video_cleanup")

RETENTION_DAYS = int(os.environ.get("VIDEO_RETENTION_DAYS", "7"))
# Retention is coarse, low-urgency work — once an hour keeps DB/FS churn tiny.
SWEEP_INTERVAL_S = 3600

# Mirror video_worker.APPS_DIR resolution so cleanup walks the same tree the
# worker renders into.
APPS_DIR = os.environ.get("APPS_DIR") or os.path.join(
    os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps")

# Intermediate render inputs to drop once out.mp4 exists (out.mp4 is kept).
_PRUNE_ENTRIES = ("screenshots", "voice.wav", "voice.mp3", "captions", "narration.txt")


def expired(now: datetime, created_at: datetime, days: int) -> bool:
    """True if ``created_at`` is strictly older than ``days`` before ``now``.

    PURE. Timezone handling is normalized to UTC so the comparison is always
    aware-vs-aware: a naive datetime (as a SQLAlchemy ``DateTime`` column may
    hand back) is treated as UTC; an aware one is converted to UTC.
    """

    def _utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return _utc(created_at) < _utc(now) - timedelta(days=days)


def prune_inputs(job_dir: str) -> None:
    """Delete the heavy render inputs under ``job_dir`` (a ``.video/<job_id>/``
    path), keeping ``out.mp4``.

    PURE filesystem op. Best-effort: missing entries are ignored and any
    per-entry OS error is logged, never raised, so a single bad file can't stop
    the sweep.
    """
    for name in _PRUNE_ENTRIES:
        path = os.path.join(job_dir, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.exception("prune_inputs: could not remove %s", path)


def _job_dir(slug: str, job_id: str) -> str:
    """``apps/<slug>/.video/<job_id>/`` — where the worker renders this job."""
    return os.path.join(APPS_DIR, slug, ".video", job_id)


# ---------------------------------------------------------------------------
# DB sweep. Below is *not* unit-tested locally because it needs a live Postgres
# connection — covered by live e2e (mirrors scheduler.py's split).
# ---------------------------------------------------------------------------
from sqlalchemy import delete, select  # noqa: E402

from db import session  # noqa: E402
from video_models import VideoJob  # noqa: E402


async def _sweep_once() -> None:
    """One retention pass (mirrors scheduler._tick_once). Kept thin-callable so
    ``video_cleanup_loop`` only owns the sleep/retry:

      (a) prune inputs for every ``done`` job whose ``out.mp4`` exists on disk;
      (b) wipe the whole job dir + delete the row for every job whose
          ``created_at`` is older than ``RETENTION_DAYS``.
    """
    now = datetime.now(timezone.utc)

    # (a) Prune inputs of finished jobs that still have out.mp4 on disk.
    async with session() as s:
        done_jobs = (await s.execute(
            select(VideoJob).where(VideoJob.status == "done")
        )).scalars().all()
    for job in done_jobs:
        job_dir = _job_dir(job.slug, str(job.id))
        if os.path.exists(os.path.join(job_dir, "out.mp4")):
            prune_inputs(job_dir)

    # (b) Expire old jobs: remove the whole job dir, then delete the rows.
    async with session() as s:
        all_jobs = (await s.execute(select(VideoJob))).scalars().all()
    expired_ids = []
    for job in all_jobs:
        if job.created_at is not None and expired(now, job.created_at, RETENTION_DAYS):
            shutil.rmtree(_job_dir(job.slug, str(job.id)), ignore_errors=True)
            expired_ids.append(job.id)
    if expired_ids:
        async with session() as s:
            await s.execute(delete(VideoJob).where(VideoJob.id.in_(expired_ids)))
            await s.commit()
        logger.info("video_cleanup: expired %d old job(s)", len(expired_ids))


async def video_cleanup_loop() -> None:
    """Main loop: sweep, sleep, forever (mirrors scheduler.schedule_tick_loop).
    Each pass is wrapped so a transient DB/FS error never kills the loop."""
    logger.info("video_cleanup_loop started")
    while True:
        try:
            await _sweep_once()
        except Exception:
            logger.exception("video_cleanup sweep failed")
        await asyncio.sleep(SWEEP_INTERVAL_S)
