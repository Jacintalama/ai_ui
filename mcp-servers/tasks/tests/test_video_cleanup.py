"""Offline tests for video_cleanup.

The pure retention predicate (`expired`) and the filesystem input-prune
(`prune_inputs`) run with no DB and are exercised for real here. The DB sweep
(`_sweep_once`) needs a live Postgres connection, so its smoke test is guarded
by `_HAVE_DB` and skipped offline.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from video_cleanup import expired, prune_inputs


def test_expired_true_false():
    now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
    # 8 days old > 7-day retention -> expired
    assert expired(now, now - timedelta(days=8), 7) is True
    # 1 day old < 7-day retention -> not expired
    assert expired(now, now - timedelta(days=1), 7) is False
    # exactly 7 days old is NOT strictly older than the cutoff -> not expired
    assert expired(now, now - timedelta(days=7), 7) is False

    # Boundary: a NAIVE created_at is treated as UTC, same verdict as aware.
    naive_old = (now - timedelta(days=8)).replace(tzinfo=None)
    assert expired(now, naive_old, 7) is True
    naive_recent = (now - timedelta(days=1)).replace(tzinfo=None)
    assert expired(now, naive_recent, 7) is False

    # Boundary: a NAIVE now is also handled without raising.
    assert expired(now.replace(tzinfo=None), now - timedelta(days=8), 7) is True


def test_prune_inputs_keeps_out_mp4(tmp_path):
    job = tmp_path / ".video" / "job-abc"
    (job / "screenshots").mkdir(parents=True)
    (job / "screenshots" / "screenshot-1.png").write_bytes(b"img")
    (job / "captions").mkdir()
    (job / "captions" / "cap-1.png").write_bytes(b"cap")
    (job / "voice.wav").write_bytes(b"wav")
    (job / "voice.mp3").write_bytes(b"mp3")
    (job / "narration.txt").write_text("hello")
    (job / "out.mp4").write_bytes(b"video")

    prune_inputs(str(job))

    # Screenshots are kept now (re-render / add-scene reuses them).
    assert (job / "screenshots").exists()
    assert not (job / "captions").exists()
    assert not (job / "voice.wav").exists()
    assert not (job / "voice.mp3").exists()
    assert not (job / "narration.txt").exists()
    # The finished render survives, byte-for-byte.
    assert (job / "out.mp4").exists()
    assert (job / "out.mp4").read_bytes() == b"video"


def test_prune_inputs_keeps_screenshots(tmp_path):
    from video_cleanup import prune_inputs
    d = tmp_path
    (d / "screenshots").mkdir(); (d / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    (d / "captions").mkdir(); (d / "captions" / "scene-1.png").write_bytes(b"x")
    (d / "narration.txt").write_text("n")
    (d / "voice.mp3").write_bytes(b"v")
    (d / "out.mp4").write_bytes(b"m")
    prune_inputs(str(d))
    assert (d / "screenshots").exists()
    assert (d / "out.mp4").exists()
    assert not (d / "captions").exists()
    assert not (d / "narration.txt").exists()
    assert not (d / "voice.mp3").exists()


def test_cap_version_files_keeps_newest_and_protected(tmp_path):
    from video_cleanup import cap_version_files
    for n in range(1, 8):
        (tmp_path / f"out-v{n}.mp4").write_bytes(b"x")
    cap_version_files(str(tmp_path), 5, {"out-v2.mp4"})
    remaining = sorted(p.name for p in tmp_path.glob("out-v*.mp4"))
    assert remaining == ["out-v2.mp4", "out-v3.mp4", "out-v4.mp4",
                         "out-v5.mp4", "out-v6.mp4", "out-v7.mp4"]


def test_prune_inputs_missing_entries_is_best_effort(tmp_path):
    # A job dir holding only out.mp4 must prune cleanly (no missing-file error).
    job = tmp_path / ".video" / "job-empty"
    job.mkdir(parents=True)
    (job / "out.mp4").write_bytes(b"video")

    prune_inputs(str(job))

    assert (job / "out.mp4").exists()


# --- DB sweep: needs a live Postgres; skipped offline ----------------------
try:
    import asyncpg  # noqa: F401

    _HAVE_DB = bool(os.environ.get("DATABASE_URL")) and os.environ.get("AIUI_TEST_DB") == "1"
except Exception:  # pragma: no cover - asyncpg always present in CI/container
    _HAVE_DB = False


@pytest.mark.skipif(
    not _HAVE_DB,
    reason="DB sweep needs live Postgres (set AIUI_TEST_DB=1 + DATABASE_URL)",
)
async def test_sweep_once_smoke():
    # Just assert one pass runs to completion without raising against a live DB.
    from video_cleanup import _sweep_once

    await _sweep_once()
