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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, select

from auth import AdminUser, current_admin
from db import session
from models import TaskItem  # for slug ownership via _require_role
from routes_projects import _require_role, _validate_slug
from video_capability import verify_video_capability
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


def _coerce_job_id(job_id: str) -> uuid.UUID:
    """Parse a path job_id into a UUID, treating a malformed id as a missing
    job (404) rather than letting it bubble up as a 500."""
    try:
        return uuid.UUID(str(job_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Video job not found")


@router.get("/{job_id}")
async def job_status(
    job_id: str,
    user: AdminUser = Depends(current_admin),
) -> dict:
    """Poll one video job's status.

    Auth: a logged-in admin gateway identity (`current_admin` -> 401 with no
    identity headers). Admins see any job; otherwise the caller must be at least
    a 'viewer' on the job's project (403 if not a member).

    `queue_position` is the number of still-queued jobs created before this one
    (0 once the job leaves the queue). `output_available` is true only when the
    render finished and an output file path is recorded.
    """
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = await s.get(VideoJob, jid)
        if job is None:
            raise HTTPException(status_code=404, detail="Video job not found")
        if user.is_admin:
            pass
        else:
            await _require_role(
                s, job.slug, user.email, "viewer", is_admin=user.is_admin
            )
        queue_position = 0
        if job.status == "queued":
            queue_position = (
                await s.execute(
                    select(func.count())
                    .select_from(VideoJob)
                    .where(
                        and_(
                            VideoJob.status == "queued",
                            VideoJob.created_at < job.created_at,
                        )
                    )
                )
            ).scalar() or 0
        output_available = job.status == "done" and job.output_path is not None
        return {
            "id": str(job.id),
            "status": job.status,
            "queue_position": queue_position,
            "error": job.error,
            "output_available": output_available,
        }


@router.get("/{job_id}/download")
async def download(job_id: str, request: Request) -> FileResponse:
    """Stream the rendered `out.mp4` for a finished job.

    Two authorization paths, capability FIRST so the no-login deep link works:
      1. A valid `video_dl` capability (header `X-Video-Capability` or `?cap=`)
         bound to THIS exact slug + job_id. This path is resolved WITHOUT
         `current_admin`, so it works behind the gateway's `X-User-Admin: false`.
      2. Otherwise, a logged-in member with at least 'viewer' on the project.
    If neither authorizes -> 403. We resolve auth before any DB round-trip so an
    unauthorized caller is rejected without a database hit.
    """
    cap_raw = (
        request.headers.get("x-video-capability")
        or request.query_params.get("cap")
        or ""
    ).strip()
    cap_data = verify_video_capability(cap_raw) if cap_raw else None
    cap_matches_job = bool(cap_data and cap_data.get("video_job_id") == str(job_id))

    # Member identity from the trusted gateway headers (may be absent for a
    # capability-only deep-link caller — that's allowed).
    member_email = request.headers.get("x-user-email", "").strip().lower()
    member_is_admin = (
        request.headers.get("x-user-admin", "").strip().lower() == "true"
    )

    # Fail fast (no DB) when there's neither a job-bound capability nor a login.
    if not cap_matches_job and not member_email:
        raise HTTPException(status_code=403, detail="Not authorized to download")

    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = await s.get(VideoJob, jid)
        if job is None:
            raise HTTPException(status_code=404, detail="Video job not found")
        # A capability authorizes only its exact slug + job; otherwise a member.
        if cap_matches_job and cap_data.get("slug") == job.slug:
            pass
        elif member_email:
            await _require_role(
                s, job.slug, member_email, "viewer", is_admin=member_is_admin
            )
        else:
            raise HTTPException(status_code=403, detail="Not authorized to download")
        if (
            job.status != "done"
            or not job.output_path
            or not os.path.exists(job.output_path)
        ):
            raise HTTPException(status_code=404, detail="Video not ready")
        output_path = job.output_path
    return FileResponse(
        output_path, media_type="video/mp4", filename=f"{job_id}.mp4"
    )
