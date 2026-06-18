"""DB helpers for video render versions (tasks.video_job_versions)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from video_models import VideoJobVersion


async def next_version_no(s: AsyncSession, job_id: uuid.UUID) -> int:
    current_max = (await s.execute(
        select(func.max(VideoJobVersion.version_no))
        .where(VideoJobVersion.job_id == job_id)
    )).scalar()
    return (current_max or 0) + 1


async def record_version(
    s: AsyncSession, job_id: uuid.UUID, version_no: int,
    plan_json: dict, summary: str | None, output_path: str | None,
) -> VideoJobVersion:
    v = VideoJobVersion(
        id=uuid.uuid4(), job_id=job_id, version_no=version_no,
        plan_json=plan_json, summary=summary, output_path=output_path,
    )
    s.add(v)
    return v


async def list_versions(s: AsyncSession, job_id: uuid.UUID) -> list[VideoJobVersion]:
    return list((await s.execute(
        select(VideoJobVersion).where(VideoJobVersion.job_id == job_id)
        .order_by(VideoJobVersion.version_no)
    )).scalars().all())


async def find_version(
    s: AsyncSession, job_id: uuid.UUID, version_no: int,
) -> VideoJobVersion | None:
    return (await s.execute(
        select(VideoJobVersion)
        .where(VideoJobVersion.job_id == job_id,
               VideoJobVersion.version_no == version_no)
    )).scalar_one_or_none()
