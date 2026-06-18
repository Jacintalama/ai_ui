"""Preview API: file tree, file content, app runner."""
import asyncio
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app_runner import get_status, start_preview, stop_preview
from auth import AdminUser, current_admin, current_admin_or_capability
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


@router.get("/{task_id}/files")
async def list_files(task_id: UUID, user: AdminUser = Depends(current_admin_or_capability)):
    item = await _get_build_task(task_id)
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    if not app_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"App directory not found: apps/{item.built_app_slug}")
    files = await asyncio.to_thread(_walk_app_files, app_dir)
    return {"slug": item.built_app_slug, "files": files}


@router.get("/{task_id}/files/{file_path:path}")
async def read_file(task_id: UUID, file_path: str, user: AdminUser = Depends(current_admin_or_capability)):
    item = await _get_build_task(task_id)
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
async def preview_start(task_id: UUID, user: AdminUser = Depends(current_admin_or_capability)):
    item = await _get_build_task(task_id)
    try:
        port = await start_preview(item.built_app_slug)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "started", "port": port, "slug": item.built_app_slug}


@router.post("/{task_id}/preview/stop")
async def preview_stop(task_id: UUID, user: AdminUser = Depends(current_admin_or_capability)):
    await stop_preview()
    return {"status": "stopped"}


@router.get("/{task_id}/preview/status")
async def preview_status(task_id: UUID, user: AdminUser = Depends(current_admin_or_capability)):
    item = await _get_build_task(task_id)
    status = get_status(item.built_app_slug)
    return status or {"running": False}
