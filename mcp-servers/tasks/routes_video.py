"""POST /api/video-jobs/upload — screenshot upload for video jobs.

Video generation is open to any logged-in user: there is no project to be a
member of. Each video is owned by its creator (user_email) and identified by
its job id URL. A user may only read or mutate their OWN videos; an admin may
act on anyone's. The caller supplies a free-text title; the slug is generated
internally (vid-<job_id8>) only to lay out the on-disk screenshot directory.

Accepts multipart/form-data with:
  - title (str): a user-typed name for the video (1-200 chars)
  - prompt (str): what the narrated slideshow should show (1-2000 chars)
  - files (list of UploadFile): 1-12 screenshot images

Guard order is chosen so the cheapest checks fire first and no disk write or
DB round-trip happens for a request we are going to reject:
  1. VIDEO_ENABLED kill switch            -> 503 if the feature is turned off
  2. current_user (FastAPI dependency)    -> 401 if no gateway identity headers
  3. file-count cap                        -> 400 if 0 or > MAX_FILES files
  4. free-disk guard                       -> 507 if the box is low on storage
  5. per-file size cap + validate_screenshot -> 413 / 400 on reject
  6. per-user daily rate limit (DB COUNT)  -> 429 over VIDEO_MAX_PER_USER_PER_DAY
Only after every guard passes do we write the screenshots to disk and insert
the queued VideoJob row.

The kill switch is checked first (before auth) so a dark deploy with
VIDEO_ENABLED=false refuses uploads entirely. The free-disk guard is a cheap,
no-DB check, so it runs before any file is read; both it and the rate limit run
before any file is written, so a flooding user is rejected before any disk is
consumed.
"""
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, update

from auth import CurrentUser, current_user
from db import session
from templates_video.style_config import STYLE_CONFIGS
from video_voices import DEFAULT_VOICE_ID, is_valid_voice, voice_catalog
from heavy_lock import enough_free_disk
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

ALLOWED_URL_HOSTS = {
    h.strip().lower()
    for h in os.environ.get(
        "VIDEO_URL_INTAKE_ALLOWED_HOSTS",
        "cdn.discordapp.com,media.discordapp.net",
    ).split(",")
    if h.strip()
}


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


def _next_screenshot_index(existing: list[str]) -> int:
    """Next screenshot number = max existing 'screenshot-N.png' suffix + 1 (1 if none)."""
    nums = [
        int(m.group(1))
        for name in existing
        if (m := re.match(r"screenshot-(\d+)\.", name))
    ]
    return (max(nums) + 1) if nums else 1


class RefineRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class RevertRequest(BaseModel):
    version_no: int


class DraftRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=2000)
    style: str = Field("clean_product_demo", max_length=50)
    voice: str = Field(DEFAULT_VOICE_ID, max_length=50)


@router.post("/draft", status_code=201)
async def create_draft(body: DraftRequest, user: CurrentUser = Depends(current_user)) -> dict:
    """Create a 'collecting' draft video job (no screenshots yet) for the Discord
    wizard. The render worker only picks 'queued' jobs, so a draft is inert until
    POST /{job_id}/queue flips it. Daily limit is NOT charged here (only at queue)."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    if body.style not in STYLE_CONFIGS:
        raise HTTPException(400, f"Unknown style: {body.style}")
    if not is_valid_voice(body.voice):
        raise HTTPException(400, f"Unknown voice: {body.voice}")
    job_id = uuid.uuid4()
    slug = f"vid-{job_id.hex[:8]}"
    async with session() as s:
        s.add(VideoJob(id=job_id, slug=slug, user_email=user.email, prompt=body.prompt,
                       title=body.title, style=body.style, voice=body.voice, status="collecting"))
        await s.commit()
    return {"id": str(job_id), "slug": slug, "status": "collecting"}


@router.post("/upload", status_code=201)
async def upload(
    title: str = Form(..., min_length=1, max_length=200),
    prompt: str = Form(..., min_length=1, max_length=2000),
    style: str = Form("clean_product_demo", max_length=50),
    voice: str = Form(DEFAULT_VOICE_ID, max_length=50),
    files: list[UploadFile] = File(default_factory=list),
    user: CurrentUser = Depends(current_user),
) -> dict:
    # 1. Kill switch FIRST: a dark deploy with VIDEO_ENABLED=false refuses
    # uploads entirely, before any auth, disk, or DB work.
    if os.environ.get("VIDEO_ENABLED", "true").strip().lower() != "true":
        raise HTTPException(503, "Video generation is disabled")
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"1-{MAX_FILES} screenshots required")
    # Style is allowlist-validated against the known StyleConfigs so it can never
    # reach the render as an unknown id (and never an ffmpeg/file path).
    if style not in STYLE_CONFIGS:
        raise HTTPException(400, f"Unknown style: {style}")
    # Voice is allowlist-validated so it can only ever select a known Piper
    # model, never a user-supplied path.
    if not is_valid_voice(voice):
        raise HTTPException(400, f"Unknown voice: {voice}")
    # Disk guard (cheap, no-DB): reject a batch we have no room to store + render
    # before reading bytes into memory, and well before any disk write.
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
    # The video is owned by its creator (user_email) and identified by job_id.
    # There is no user-supplied project slug anymore; generate one internally
    # only to lay out the on-disk screenshot directory.
    job_id = uuid.uuid4()
    slug = f"vid-{job_id.hex[:8]}"
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
                title=title,
                style=style,
                voice=voice,
                status="queued",
            )
        )
        await s.commit()
    return {"id": str(job_id), "status": "queued"}


@router.get("")
async def list_jobs(user: CurrentUser = Depends(current_user)) -> dict:
    """List the calling user's own video jobs, newest first.

    Auth: any logged-in gateway identity (`current_user` -> 401 with no identity
    headers). Each user sees only their own videos (filtered by user_email).

    Only the columns needed for a "my videos" landing page are selected so the
    query stays robust even when the deployed database lacks newer columns.
    `output_available` is true only when an output file path is recorded.
    """
    async with session() as s:
        rows = (await s.execute(
            select(VideoJob.id, VideoJob.title, VideoJob.status, VideoJob.created_at,
                   VideoJob.current_version_no, VideoJob.output_path)
            .where(VideoJob.user_email == user.email)
            .order_by(VideoJob.created_at.desc())
        )).all()
    return {"videos": [{
        "id": str(r.id),
        "title": r.title,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "current_version_no": r.current_version_no,
        "output_available": bool(r.output_path),
    } for r in rows]}


# Registered BEFORE "/{job_id}" so the literal "voices" path is not captured as
# a job id. No auth: it is a static, non-sensitive catalog (the preview clips
# are public static files) used by the create-form picker.
@router.get("/voices")
async def voices() -> dict:
    """The selectable narration voices for the create-form picker."""
    return {"voices": voice_catalog(), "default": DEFAULT_VOICE_ID}


# Registered BEFORE "/{job_id}" so the literal "current-draft" path is not
# captured as a job id.
@router.get("/current-draft")
async def current_draft(user: CurrentUser = Depends(current_user)) -> dict:
    """The caller's newest in-progress draft ('collecting') + its screenshot count.
    404 when there is no draft. Used by `/video add` to find which draft to attach to."""
    async with session() as s:
        job = (await s.execute(
            select(VideoJob)
            .where(and_(VideoJob.user_email == user.email, VideoJob.status == "collecting"))
            .order_by(VideoJob.created_at.desc())
        )).scalars().first()
    if job is None:
        raise HTTPException(404, "No draft in progress")
    return {"id": str(job.id), "slug": job.slug, "title": job.title,
            "style": job.style, "voice": job.voice,
            "screenshot_count": len(_list_screenshots(job.slug, str(job.id)))}


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
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Poll one video job's status.

    Auth: any logged-in gateway identity (`current_user` -> 401 with no identity
    headers). A user may only read their own video; an admin may read anyone's
    (-> 403 otherwise).

    `queue_position` is the number of still-queued jobs created before this one
    (0 once the job leaves the queue). `output_available` is true only when the
    render finished and an output file path is recorded.
    """
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = await s.get(VideoJob, jid)
        if job is None:
            raise HTTPException(status_code=404, detail="Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
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
            "slug": job.slug,
            "title": job.title,
            "status": job.status,
            "queue_position": queue_position,
            "error": job.error,
            "output_available": output_available,
            "conversation": job.conversation or [],
            "current_version_no": job.current_version_no,
            "pending": latest_pending_proposal(job.conversation or []) is not None,
            "plan": job.plan_json,
        }


@router.get("/{job_id}/download")
async def download(
    job_id: str, request: Request, version: int | None = None
) -> FileResponse:
    """Stream the rendered `out.mp4` for a finished job.

    Two authorization paths, capability FIRST so the no-login deep link works:
      1. A valid `video_dl` capability (header `X-Video-Capability` or `?cap=`)
         bound to THIS exact slug + job_id. This path is resolved WITHOUT
         `current_admin`, so it works behind the gateway's `X-User-Admin: false`.
      2. Otherwise, a logged-in member who is the OWNER of the job
         (gateway `X-User-Email` == job.user_email) OR an admin
         (`X-User-Admin: true`).
    If neither authorizes -> 403. We resolve auth before any DB round-trip so an
    unauthorized caller is rejected without a database hit.

    The optional `?version=N` query param streams a specific recorded version's
    output instead of the job's current `output_path` (404 if that version does
    not exist or its file is missing). Auth is identical either way.
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
        # A capability authorizes only its exact slug + job; otherwise the
        # logged-in member must be the job's owner or an admin.
        if cap_matches_job and cap_data.get("slug") == job.slug:
            pass
        elif member_email and (member_email == job.user_email or member_is_admin):
            pass
        else:
            raise HTTPException(status_code=403, detail="Not authorized to download")
        if version is not None:
            # Serve a specific recorded version's file (the same open session
            # resolves it). The job's current render status is irrelevant here.
            v = await find_version(s, jid, version)
            if v is None:
                raise HTTPException(status_code=404, detail="Version not found")
            if not v.output_path or not os.path.exists(v.output_path):
                raise HTTPException(status_code=404, detail="Video not ready")
            output_path = v.output_path
        else:
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
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Chat-refine a job's plan: returns either a clarifying question or a
    proposed (un-applied) plan, persisting the conversation either way.

    Auth: any logged-in gateway identity (current_user -> 401); the caller must
    own the video or be an admin (-> 403). The proposal is recorded as a pending
    turn; POST /apply renders it.
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
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
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
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Apply the latest pending proposal: swap in its plan and re-queue a render.

    Auth: current_user (-> 401); the caller must own the video or be an admin
    (-> 403). Returns 409 if there is nothing pending to apply, 422 if the
    proposed plan is no longer valid against the screenshots currently on disk.
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
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
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
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Add more screenshots to an existing job (used mid-chat to give the
    refiner new material). Mirrors the upload endpoint's validation.

    Auth: current_user (-> 401); the caller must own the video or be an admin
    (-> 403). Guard order: kill switch (503), missing job (404), ownership
    (403), free-disk (507), file-count cap of existing+new <= MAX_FILES (400,
    checked before any file bytes are read), then per-file size (413),
    cumulative-with-existing total (413), and per-file content validation (400).
    New files continue the screenshot-N numbering after the existing highest.
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
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        slug = job.slug
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
    shots_dir = _apps_dir() / slug / ".video" / str(jid) / "screenshots"
    existing = _list_screenshots(slug, str(jid))
    existing_count = len(existing)
    start = _next_screenshot_index(existing)
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
    for i, body in enumerate(raw):
        (shots_dir / f"screenshot-{start + i}.png").write_bytes(body)
    return {"screenshots": _list_screenshots(slug, str(jid))}


class ScreenshotUrlsRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=MAX_FILES)


def _check_intake_url(u: str) -> None:
    """SSRF guard: only https URLs on the Discord CDN allow-list may be fetched.
    Fails closed (400) for any other scheme or host."""
    p = urlparse(u)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_URL_HOSTS:
        raise HTTPException(400, "screenshot URL host not allowed")


@router.post("/{job_id}/screenshots-by-url")
async def add_screenshots_by_url(
    job_id: str,
    body: ScreenshotUrlsRequest,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Add screenshots to a job by fetching image URLs server-side. Mirrors
    /screenshots guards (count/size/validation/disk) and screenshot-N numbering.
    SSRF guard restricts fetches to the Discord CDN allow-list, validated up front
    before any DB work."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    for u in body.urls:
        _check_intake_url(u)
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(
            select(VideoJob).where(VideoJob.id == jid)
        )).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        slug = job.slug
    if not enough_free_disk(
        str(_apps_dir()), int(os.environ.get("VIDEO_MIN_FREE_DISK_MB", "2000"))
    ):
        raise HTTPException(507, "Insufficient storage; try again later")
    shots_dir = _apps_dir() / slug / ".video" / str(jid) / "screenshots"
    existing = _list_screenshots(slug, str(jid))
    start = _next_screenshot_index(existing)
    if len(existing) + len(body.urls) > MAX_FILES:
        raise HTTPException(400, f"max {MAX_FILES} screenshots per job")
    total = sum(
        (shots_dir / name).stat().st_size
        for name in existing
        if (shots_dir / name).is_file()
    )
    raw: list[bytes] = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for url in body.urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError:
                raise HTTPException(400, "could not fetch screenshot URL")
            data = resp.content
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, "screenshot too large (max 10 MB)")
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "batch too large")
            try:
                validate_screenshot(urlparse(url).path.rsplit("/", 1)[-1] or "x.png", data)
            except ScreenshotRejected as e:
                raise HTTPException(400, str(e))
            raw.append(data)
    shots_dir.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(raw):
        (shots_dir / f"screenshot-{start + i}.png").write_bytes(data)
    shots = _list_screenshots(slug, str(jid))
    return {"screenshots": shots, "count": len(shots)}


@router.get("/{job_id}/versions")
async def versions(job_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    """List saved render versions for a job (newest state via current/available flags).

    Auth: current_user (-> 401); the caller must own the video or be an admin
    (-> 403).
    """
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (
            await s.execute(select(VideoJob).where(VideoJob.id == jid))
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        vs = await list_versions(s, jid)
        return {
            "versions": [
                {
                    "version_no": v.version_no,
                    "summary": v.summary,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "current": v.version_no == job.current_version_no,
                    "available": bool(v.output_path and os.path.exists(v.output_path)),
                }
                for v in vs
            ]
        }


@router.post("/{job_id}/revert")
async def revert(
    job_id: str,
    body: RevertRequest,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Revert a job to an earlier version: instant if its file exists, else re-render.

    Auth: current_user (-> 401); the caller must own the video or be an admin
    (-> 403).
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
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        v = await find_version(s, jid, body.version_no)
        if v is None:
            raise HTTPException(404, "Version not found")
        convo = append_turn(
            job.conversation or [], "assistant", "note", f"Reverted to v{v.version_no}."
        )
        if v.output_path and os.path.exists(v.output_path):
            await s.execute(
                update(VideoJob)
                .where(VideoJob.id == jid)
                .values(
                    plan_json=v.plan_json,
                    output_path=v.output_path,
                    current_version_no=v.version_no,
                    conversation=convo,
                )
            )
            await s.commit()
            return {"status": "reverted", "output_available": True}
        await s.execute(
            update(VideoJob)
            .where(VideoJob.id == jid)
            .values(
                plan_json=v.plan_json,
                status="queued",
                conversation=convo,
                pending_summary=f"Revert to v{v.version_no}",
            )
        )
        await s.commit()
        return {"status": "queued", "output_available": False}


class DraftPatch(BaseModel):
    style: str | None = Field(None, max_length=50)
    voice: str | None = Field(None, max_length=50)


@router.post("/{job_id}/draft-set")
async def update_draft(job_id: str, body: DraftPatch, user: CurrentUser = Depends(current_user)) -> dict:
    """Update style/voice on a 'collecting' draft (the Discord select handlers)."""
    if not _video_enabled():
        raise HTTPException(503, "Video generation is disabled")
    jid = _coerce_job_id(job_id)
    async with session() as s:
        job = (await s.execute(select(VideoJob).where(VideoJob.id == jid))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Video job not found")
        if not user.is_admin and job.user_email != user.email:
            raise HTTPException(403, "Not authorized for this video")
        if job.status != "collecting":
            raise HTTPException(409, "Video is not a draft")
        vals = {}
        if body.style is not None:
            if body.style not in STYLE_CONFIGS:
                raise HTTPException(400, f"Unknown style: {body.style}")
            vals["style"] = body.style
        if body.voice is not None:
            if not is_valid_voice(body.voice):
                raise HTTPException(400, f"Unknown voice: {body.voice}")
            vals["voice"] = body.voice
        if vals:
            await s.execute(update(VideoJob).where(VideoJob.id == jid).values(**vals))
            await s.commit()
    return {"status": "ok", **vals}
