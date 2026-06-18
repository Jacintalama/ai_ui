"""Shared heavy-job advisory lock + RAM/disk guards.

One Postgres advisory lock keyed `hashtext('heavy_job')` that both renders and
builds acquire, so a render and a build can never run at once (this is what
prevents the OOM that would otherwise hit existing features). Renders try it
non-blocking via `pg_try_advisory_lock` and defer if it is held. The render
worker also keeps a read-only `build_in_flight` check as a belt-and-suspenders
guard for a build that began before the worker woke.

Resource guards read `/proc/meminfo` (MemAvailable) and `shutil.disk_usage`.
"""
import shutil
from contextlib import asynccontextmanager

from sqlalchemy import text

_LOCK_KEY = "heavy_job"


def _available_ram_mb() -> int:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return 0


def _free_disk_mb(path: str) -> int:
    return shutil.disk_usage(path).free // (1024 * 1024)


def enough_free_ram(min_mb: int) -> bool:
    return _available_ram_mb() >= min_mb


def enough_free_disk(path: str, min_mb: int) -> bool:
    return _free_disk_mb(path) >= min_mb


async def build_in_flight(s) -> bool:
    """True if an app build is currently running (render must yield to it)."""
    row = (await s.execute(text(
        "SELECT 1 FROM tasks.items WHERE status='running' LIMIT 1"
    ))).first()
    return row is not None


@asynccontextmanager
async def try_heavy_lock(s):
    """Non-blocking session-level advisory lock. Yields True if acquired."""
    got = (await s.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": _LOCK_KEY}
    )).scalar()
    try:
        yield bool(got)
    finally:
        if got:
            await s.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": _LOCK_KEY})
            await s.commit()


@asynccontextmanager
async def heavy_lock(s):
    """Blocking session-level advisory lock on the shared ``heavy_job`` key.

    Unlike :func:`try_heavy_lock` (non-blocking, used by the video render worker
    so it can defer when the box is busy), this WAITS until the lock is free and
    then holds it for the duration of the ``with`` block. App builds use this so
    a build queues behind an in-flight render instead of failing, and by the
    same single global lock a render cannot start while a build holds it. Pass a
    dedicated session so the lock's lifetime is exactly this block; the finally
    always releases it (success, failure, timeout, or cancellation).
    """
    await s.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": _LOCK_KEY})
    try:
        yield
    finally:
        await s.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": _LOCK_KEY})
        await s.commit()
