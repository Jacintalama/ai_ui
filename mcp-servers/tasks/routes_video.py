"""POST /api/video-jobs/upload — member-auth screenshot upload for video jobs.

Accepts multipart/form-data with:
  - slug (str): the project the screenshots belong to (path-injection guarded)
  - prompt (str): what the narrated slideshow should show (1-2000 chars)
  - files (list of UploadFile): 1-12 screenshot images

Guard order is chosen so the cheapest checks fire first and no disk write or
DB round-trip happens for a request we are going to reject:
  1. VIDEO_ENABLED kill switch            -> 503 if the feature is turned off
  2. current_admin (FastAPI dependency)   -> 401 if no gateway identity headers
  3. _validate_slug                        -> 400 on an unsafe slug
  4. file-count cap                        -> 400 if 0 or > MAX_FILES files
  5. free-disk guard                       -> 507 if the box is low on storage
  6. _require_role(..., "editor")          -> 403 unless the user can edit the slug
  7. per-file size cap + validate_screenshot -> 413 / 400 on reject
  8. per-user daily rate limit (DB COUNT)  -> 429 over VIDEO_MAX_PER_USER_PER_DAY
Only after every guard passes do we write the screenshots to disk and insert
the queued VideoJob row.

The kill switch is checked first (before auth) so a dark deploy with
VIDEO_ENABLED=false refuses uploads entirely. The free-disk guard is a cheap,
no-DB check, so it runs before the role lookup (keeping with "cheap, no-DB
first"); both it and the rate limit run before any file is written, so a
flooding user is rejected before any disk is consumed.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, update

from auth import AdminUser, current_admin
from db import session
from heavy_lock import enough_free_disk
from models import TaskItem  # for slug ownership via _require_role
from routes_projects import _require_role, _validate_slug
from video_capability import verify_video_capability
from video_models import VideoJob
from video_plan import validate_plan
from video_refine import (
    RefineUnavailable,
    append_turn,
    keep_only_latest_proposal_plan,
    latest_pending_proposal,
    mark_proposal_applied,
    refine_plan,
)
from video_validation import ScreenshotRejected, validate_screenshot
from video_versions import find_version, list_versions

router = APIRouter(prefix="/api/video-jobs")

logger = logging.getLogger("routes_video")

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


def _video_enabled() -> bool:
    """The VIDEO_ENABLED kill switch (defaults on). A dark deploy with
    VIDEO_ENABLED=false refuses all video operations."""
    return os.environ.get("VIDEO_ENABLED", "true").strip().lower() == "true"


def _list_screenshots(slug: str, job_id: str) -> list[str]:
    """Sorted screenshot filenames for a job ([] if the directory is missing).

    Mirrors the upload endpoint's on-disk layout:
    <APPS_DIR>/<slug>/.video/<job_id>/screenshots/screenshot-N.png
    """
    shots_dir = _apps_dir() / slug / ".video" / job_id / "screenshots"
    if not shots_dir.is_dir():
        return []
    return sorted(p.name for p in shots_dir.iterdir() if p.is_file())


class RefineRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class RevertRequest(BaseModel):
    version_no: int


@router.post("/upload", status_code=201)
async def upload(
    slug: str = Form(...),
    prompt: str = Form(..., min_length=1, max_length=2000),
    files: list[UploadFile] = File(default_factory=list),
    user: AdminUser = Depends(current_admin),
) -> dict:
    # 1. Kill switch FIRST: a dark deploy with VIDEO_ENABLED=false refuses
    # uploads entirely, before any auth-role, disk, or DB work.
    if os.environ.get("VIDEO_ENABLED", "true").strip().lower() != "true":
        raise HTTPException(503, "Video generation is disabled")
    _validate_slug(slug)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"1-{MAX_FILES} screenshots required")
    # Disk guard (cheap, no-DB): reject a batch we have no room to store + render
    # before the role DB round-trip, before reading bytes into memory, and well
    # before any disk write.
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
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
    # Per-user daily rate limit: reject a flooding user before any disk write.
    cutoff = datetime.utcnow() - timedelta(hours=24)
    async with session() as s:
        used = (
            await s.execute(
                select(func.count())
                .select_from(VideoJob)
                .where(
                    and_(
                        VideoJob.user_email == user.email,
                        VideoJob.created_at >= cutoff,
                    )
                )
            )
        ).scalar() or 0
        if used >= int(os.environ.get("VIDEO_MAX_PER_USER_PER_DAY", "10")):
            raise HTTPException(429, "Daily video limit reached")
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


@router.post("/{job_id}/refine")
async def refine(
    job_id: str,
    body: RefineRequest,
    user: AdminUser = Depends(current_admin),
) -> dict:
    """Chat-refine a job's plan: returns either a clarifying question or a
    proposed (un-applied) plan, persisting the conversation either way.

    Auth: a logged-in admin gateway identity (current_admin -> 401), then at
    least 'editor' on the job's project (403). The proposal is recorded as a
    pending turn; POST /apply renders it.
    """
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    # Short session: load + authorize + snapshot what we need, then release the
    # pooled connection BEFORE the slow external Claude call (avoid pool starvation).
    async with session() as s:
        job = (
            await s.execute(select(VideoJob).where(VideoJob.id == jid))
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        await _require_role(s, job.slug, user.email, "editor", is_admin=user.is_admin)
        slug = job.slug
        plan_json = job.plan_json or {}
        convo = list(job.conversation or [])
    shots = _list_screenshots(slug, str(jid))
    convo = append_turn(convo, "user", "message", body.message)
    try:
        result = await refine_plan(plan_json, shots, convo, body.message)
    except RefineUnavailable:
        raise HTTPException(503, "Refinement is unavailable (no API key)")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - transport/parse failure: surface a clean retryable error
        logger.exception("refine_plan failed for video job %s", jid)
        raise HTTPException(502, "Refinement failed, please try again")
    if result["action"] == "propose":
        convo = append_turn(
            convo,
            "assistant",
            "proposal",
            result["message"],
            plan=result["plan"],
            applied=False,
        )
        convo = keep_only_latest_proposal_plan(convo)
    else:
        convo = append_turn(convo, "assistant", "question", result["message"])
    async with session() as s:
        await s.execute(
            update(VideoJob).where(VideoJob.id == jid).values(conversation=convo)
        )
        await s.commit()
    return {
        "action": result["action"],
        "message": result["message"],
        "can_apply": result["action"] == "propose",
    }


@router.post("/{job_id}/apply")
async def apply(
    job_id: str,
    user: AdminUser = Depends(current_admin),
) -> dict:
    """Apply the latest pending proposal: swap in its plan and re-queue a render.

    Auth: current_admin (-> 401) then 'editor' on the project (-> 403). Returns
    409 if there is nothing pending to apply, 422 if the proposed plan is no
    longer valid against the screenshots currently on disk.
    """
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (
            await s.execute(select(VideoJob).where(VideoJob.id == jid))
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        await _require_role(s, job.slug, user.email, "editor", is_admin=user.is_admin)
        prop = latest_pending_proposal(job.conversation or [])
        if prop is None:
            raise HTTPException(409, "No pending change to apply")
        shots = _list_screenshots(job.slug, str(jid))
        try:
            validate_plan(prop["plan"], shots)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Proposed change is no longer valid: {exc}")
        convo = mark_proposal_applied(job.conversation or [], prop)
        convo = append_turn(
            convo, "assistant", "note", "Applying. Re-rendering your video."
        )
        await s.execute(
            update(VideoJob)
            .where(VideoJob.id == jid)
            .values(
                plan_json=prop["plan"],
                status="queued",
                conversation=convo,
                pending_summary=prop["content"],
            )
        )
        await s.commit()
    return {"status": "queued"}


@router.post("/{job_id}/screenshots")
async def add_screenshots(
    job_id: str,
    files: list[UploadFile] = File(default_factory=list),
    user: AdminUser = Depends(current_admin),
) -> dict:
    """Add more screenshots to an existing job (used mid-chat to give the
    refiner new material). Mirrors the upload endpoint's validation.

    Auth: current_admin (-> 401) then 'editor' on the job's project (-> 403).
    Guard order: kill switch (503), missing job (404), editor role, free-disk
    (507), then per-file size (413), cumulative-with-existing total (413),
    file-count cap (400), and per-file content validation (400). New files
    continue the screenshot-N numbering after the existing highest.
    """
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (
            await s.execute(select(VideoJob).where(VideoJob.id == jid))
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        await _require_role(s, job.slug, user.email, "editor", is_admin=user.is_admin)
        slug = job.slug
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
    shots_dir = _apps_dir() / slug / ".video" / str(jid) / "screenshots"
    existing = _list_screenshots(slug, str(jid))
    existing_count = len(existing)
    if not files or existing_count + len(files) > MAX_FILES:
        raise HTTPException(400, f"max {MAX_FILES} screenshots per job")
    # The cumulative cap counts what is already on disk, so a series of small
    # adds cannot smuggle past MAX_TOTAL_BYTES one batch at a time.
    total = sum(
        (shots_dir / name).stat().st_size
        for name in existing
        if (shots_dir / name).is_file()
    )
    raw = []
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
    shots_dir.mkdir(parents=True, exist_ok=True)
    for i, body in enumerate(raw, 1):
        (shots_dir / f"screenshot-{existing_count + i}.png").write_bytes(body)
    return {"screenshots": _list_screenshots(slug, str(jid))}
