"""Preview API: file tree, file content, app runner."""
import asyncio
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app_runner import get_status, start_preview, stop_preview
from auth import (AdminUser, CurrentUser, current_admin,
                  current_admin_or_capability, current_user_or_capability)
from db import session
from models import TaskItem

router = APIRouter(prefix="/api/tasks")

WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")

# Directories that exist inside apps/<slug>/ but should never appear in the
# Files tab — `.attachments` holds chat image uploads forwarded to the agent
# as vision input; `node_modules` is a build artifact.
_SKIP_DIRS = frozenset({"node_modules", ".attachments"})


def _should_include_path(parts: tuple[str, ...]) -> bool:
    """True iff none of the path components is an internal skip-dir."""
    return not any(p in _SKIP_DIRS for p in parts)


def _walk_app_files(app_dir: Path) -> list[dict]:
    """List user-facing files under apps/<slug>/, PRUNING skip-dirs during the
    walk so we never descend into node_modules (tens of thousands of files —
    a memory/CPU spike on the 3.8GB host). Synchronous and blocking; call via
    asyncio.to_thread so it doesn't stall the event loop. Paths are posix."""
    out: list[dict] = []
    for root, dirs, names in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]  # prune before descending
        for name in names:
            full = Path(root) / name
            rel = full.relative_to(app_dir)
            if _should_include_path(rel.parts):
                out.append({"path": rel.as_posix(), "size": full.stat().st_size})
    out.sort(key=lambda f: f["path"])
    return out


async def _get_build_task(task_id: UUID) -> TaskItem:
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not item.built_app_slug:
        raise HTTPException(status_code=404, detail="No built app for this task")
    return item


async def _owned_build_task(task_id: UUID, user, min_role: str) -> TaskItem:
    """The task, if this caller may act on its app at `min_role` or better.

    These routes had NO ownership check — `_get_build_task` only asserts the
    task exists and carries a slug, and the admin header was the entire
    protection. `read_file` returns file contents, so relaxing the gate without
    this would hand every signed-in account every user's source.

    Scoped by project role rather than assignee so invited members keep the
    access they already have, matching the export routes.
    """
    item = await _get_build_task(task_id)
    # Admin short-circuit BEFORE opening a session: _require_role returns
    # "owner" unconditionally for an admin, so the round-trip buys nothing.
    if getattr(user, "is_admin", False):
        return item
    from routes_projects import _require_role
    async with session() as s:
        await _require_role(s, item.built_app_slug, user.email, min_role)
    return item


@router.get("/{task_id}/files")
async def list_files(task_id: UUID, user: CurrentUser = Depends(current_user_or_capability)):
    item = await _owned_build_task(task_id, user, 'viewer')
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    if not app_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"App directory not found: apps/{item.built_app_slug}")
    files = await asyncio.to_thread(_walk_app_files, app_dir)
    return {"slug": item.built_app_slug, "files": files}


@router.get("/{task_id}/files/{file_path:path}")
async def read_file(task_id: UUID, file_path: str, user: CurrentUser = Depends(current_user_or_capability)):
    item = await _owned_build_task(task_id, user, 'viewer')
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    app_dir_resolved = app_dir.resolve()
    target = (app_dir / file_path).resolve()
    if not str(target).startswith(str(app_dir_resolved)):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    try:
        rel_parts = target.relative_to(app_dir_resolved).parts
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")
    if not _should_include_path(rel_parts):
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.stat().st_size > 500_000:
        raise HTTPException(status_code=413, detail="File too large to preview")
    return {"path": file_path, "content": target.read_text(errors="replace")}


@router.post("/{task_id}/preview/start")
async def preview_start(task_id: UUID, user: CurrentUser = Depends(current_user_or_capability)):
    item = await _owned_build_task(task_id, user, 'editor')
    try:
        port = await start_preview(item.built_app_slug)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "started", "port": port, "slug": item.built_app_slug}


@router.post("/{task_id}/preview/stop")
async def preview_stop(task_id: UUID, user: CurrentUser = Depends(current_user_or_capability)):
    # Checked even though the body never needed the task: stop_preview() takes
    # no slug, so ANY caller stops whichever app is currently previewing —
    # including someone else's. Without this, opening the gate would let any
    # signed-in account kill every other user's preview by naming any task id.
    await _owned_build_task(task_id, user, 'editor')
    await stop_preview()
    return {"status": "stopped"}


@router.get("/{task_id}/preview/status")
async def preview_status(task_id: UUID, user: CurrentUser = Depends(current_user_or_capability)):
    item = await _owned_build_task(task_id, user, 'viewer')
    status = get_status(item.built_app_slug)
    return status or {"running": False}
