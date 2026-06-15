"""POST /api/video-jobs/upload — member-auth screenshot upload for video jobs.

Accepts multipart/form-data with:
  - slug (str): the project the screenshots belong to (path-injection guarded)
  - prompt (str): what the narrated slideshow should show (1-2000 chars)
  - files (list of UploadFile): 1-12 screenshot images

Guard order is chosen so the cheap, no-DB checks and auth happen before any
database round-trip:
  1. current_admin (FastAPI dependency)  -> 401 if no gateway identity headers
  2. _validate_slug                       -> 400 on an unsafe slug
  3. file-count cap                       -> 400 if 0 or > MAX_FILES files
  4. _require_role(..., "editor")         -> 403 unless the user can edit the slug
  5. per-file size cap + validate_screenshot -> 413 / 400 on reject
Only after every file is read and validated do we write to disk and insert the
queued VideoJob row.
"""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from auth import AdminUser, current_admin
from db import session
from models import TaskItem  # for slug ownership via _require_role
from routes_projects import _require_role, _validate_slug
from video_models import VideoJob
from video_validation import ScreenshotRejected, validate_screenshot

router = APIRouter(prefix="/api/video-jobs")

MAX_FILES = 12
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024


def _apps_dir() -> Path:
    return Path(
        os.environ.get("APPS_DIR")
        or os.path.join(
            os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"
        )
    )


@router.post("/upload", status_code=201)
async def upload(
    slug: str = Form(...),
    prompt: str = Form(..., min_length=1, max_length=2000),
    files: list[UploadFile] = File(default_factory=list),
    user: AdminUser = Depends(current_admin),
) -> dict:
    _validate_slug(slug)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"1-{MAX_FILES} screenshots required")
    async with session() as s:
        await _require_role(s, slug, user.email, "editor", is_admin=user.is_admin)
    total, raw = 0, []
    for f in files:
        body = await f.read(MAX_FILE_BYTES + 1)
        if len(body) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{f.filename}: max 10 MB")
        total += len(body)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(413, "batch too large")
        try:
            validate_screenshot(f.filename or "x.png", body)
        except ScreenshotRejected as e:
            raise HTTPException(400, str(e))
        raw.append(body)
    job_id = uuid.uuid4()
    shots = _apps_dir() / slug / ".video" / str(job_id) / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    for i, body in enumerate(raw, 1):
        (shots / f"screenshot-{i}.png").write_bytes(body)
    async with session() as s:
        s.add(
            VideoJob(
                id=job_id,
                slug=slug,
                user_email=user.email,
                prompt=prompt,
                status="queued",
            )
        )
        await s.commit()
    return {"id": str(job_id), "status": "queued"}
