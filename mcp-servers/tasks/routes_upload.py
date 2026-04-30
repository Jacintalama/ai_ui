"""POST /api/projects/upload — drag-and-drop project import.

Receives multipart/form-data with:
  - name (str, optional): user-supplied project name; normalized to slug
  - files (list of UploadFile): each file's filename is the relative path

Validates everything via upload_validation (no I/O), then writes files
to /workspace/ai_ui/apps/<slug>/, then inserts a tasks row with
status="completed" so the existing preview/publish pipeline takes over.

Rejects with 400 on validation failure, 409 if the slug already exists,
413 (Payload Too Large) on size/count caps, 401/403 on auth failure.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError

from auth import AdminUser, current_admin
from db import session
from models import TaskItem
from upload_validation import (
    MAX_TOTAL_BYTES,
    UploadRejected,
    normalize_rel_path,
    safe_join,
    validate_batch,
)

logger = logging.getLogger(__name__)

_APP_ROOT_FS = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui") + "/apps"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")

router = APIRouter(prefix="/api/projects")


def _slugify(raw: str) -> str:
    """Convert 'My Coffee Shop' -> 'my-coffee-shop'."""
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@router.post("/upload", status_code=201)
async def upload_project(
    name: str = Form(""),
    files: list[UploadFile] = [],
    user: AdminUser = Depends(current_admin),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    # 1. Derive slug from name or generate a random one.
    raw_slug = _slugify(name) if name else f"upload-{uuid.uuid4().hex[:8]}"
    if not _SLUG_RE.match(raw_slug):
        raise HTTPException(
            status_code=400,
            detail=(
                "project name must produce a slug like 'my-app' "
                "(2–81 chars, letters/digits/hyphens)"
            ),
        )

    # 2. Read all files into memory so we can reject the batch before touching
    #    disk. We enforce the total-size cap here with an early-out.
    raw: list[tuple[str, int, bytes]] = []
    total = 0
    for f in files:
        body = await f.read()
        size = len(body)
        total += size
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds {MAX_TOTAL_BYTES // (1024 * 1024)} MB total",
            )
        raw.append((f.filename or "", size, body))

    # 3. Validate batch — path safety, extension allowlist, depth, count caps.
    try:
        accepted = validate_batch([(p, s) for (p, s, _) in raw])
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=f"upload rejected: {exc}")

    # Build a lookup from normalized rel_path -> body bytes.
    body_by_norm: dict[str, bytes] = {}
    for raw_path, _size, body in raw:
        try:
            norm = normalize_rel_path(raw_path)
        except UploadRejected:
            continue
        if norm is not None and norm not in body_by_norm:
            body_by_norm[norm] = body

    # 4. Refuse if the slug already exists on disk.
    dest_dir = os.path.join(_APP_ROOT_FS, raw_slug)
    if os.path.exists(dest_dir):
        raise HTTPException(
            status_code=409,
            detail=f"project '{raw_slug}' already exists — pick a different name",
        )

    # 5. Write files atomically: if anything fails, remove the partial dir.
    try:
        os.makedirs(dest_dir, mode=0o755, exist_ok=False)
        for v in accepted:
            target = safe_join(dest_dir, v.rel_path)
            os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
            body = body_by_norm.get(v.rel_path)
            if body is None:
                raise UploadRejected(f"internal: no body for {v.rel_path}")
            with open(target, "wb") as out:
                out.write(body)
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    # 6. Insert a tasks row with status="completed" so preview/publish works.
    #    TaskItem has no top-level "slug" column; built_app_slug is the link.
    #    meeting_id, action_type, assignee_name, assignee_email, priority are
    #    all NOT NULL — mirror how create_task fills them for admin-created rows.
    task_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with session() as s:
        s.add(
            TaskItem(
                id=task_id,
                meeting_id=uuid.uuid4(),  # synthetic — no real meeting
                action_type="BUILD",
                assignee_name=user.email.split("@")[0],
                assignee_email=user.email,
                description=f"Uploaded project '{raw_slug}' ({len(accepted)} files).",
                priority="medium",
                status="completed",
                built_app_slug=raw_slug,
                result=f"Uploaded {len(accepted)} files into apps/{raw_slug}/.",
                completed_at=now,
            )
        )
        try:
            await s.commit()
        except IntegrityError:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(
                status_code=409,
                detail=f"project '{raw_slug}' already exists",
            )

    logger.info(
        "upload_project: slug=%s files=%d bytes=%d user=%s",
        raw_slug,
        len(accepted),
        sum(v.size for v in accepted),
        user.email,
    )

    return {
        "task_id": str(task_id),
        "slug": raw_slug,
        "files_written": len(accepted),
        "total_bytes": sum(v.size for v in accepted),
    }
