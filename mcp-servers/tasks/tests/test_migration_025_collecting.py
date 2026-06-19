"""Tests for migration 025 — 'collecting' draft status on tasks.video_jobs.

test_migration_file_includes_collecting: file-content check, no DB required.
test_collecting_status_roundtrip: inserts a VideoJob with status='collecting'
    and reads it back; skipped when no Postgres is available.
"""
import os
import pathlib
import uuid

import pytest
from sqlalchemy import select

from video_models import VideoJob

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL

_MIGRATION_FILE = (
    pathlib.Path(__file__).parent.parent / "migrations" / "025_video_collecting_status.sql"
)


def test_migration_file_includes_collecting():
    """Migration file must exist and contain both the new status value and the
    constraint name — verifiable without a database."""
    assert _MIGRATION_FILE.exists(), f"Migration file not found: {_MIGRATION_FILE}"
    sql = _MIGRATION_FILE.read_text()
    assert "collecting" in sql, "'collecting' status value missing from migration"
    assert "video_jobs_status_check" in sql, "named constraint 'video_jobs_status_check' missing from migration"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_collecting_status_roundtrip(db_session):
    """Insert a VideoJob with status='collecting' and read it back.

    Requires Postgres (aiui_test DB) — to be verified on the server at deploy.
    """
    job_id = uuid.uuid4()
    job = VideoJob(
        id=job_id,
        slug="test-collecting",
        user_email="test@example.com",
        prompt="a test video",
        status="collecting",
    )
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(
        select(VideoJob).where(VideoJob.id == job_id)
    )
    fetched = result.scalar_one()
    assert fetched.status == "collecting"
