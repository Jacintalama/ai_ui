"""Preview API: file tree, file content, app runner."""
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app_runner import get_status, start_preview, stop_preview
from auth import AdminUser, current_admin
from db import session
from models import TaskItem

router = APIRouter(prefix="/api/tasks")

WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")


async def _get_build_task(task_id: UUID) -> TaskItem:
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not item.built_app_slug:
        raise HTTPException(status_code=404, detail="No built app for this task")
    return item


@router.get("/{task_id}/files")
async def list_files(task_id: UUID, user: AdminUser = Depends(current_admin)):
    item = await _get_build_task(task_id)
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    if not app_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"App directory not found: apps/{item.built_app_slug}")
    files = []
    for p in sorted(app_dir.rglob("*")):
        if p.is_file() and "node_modules" not in p.parts:
            files.append({
                "path": str(p.relative_to(app_dir)),
                "size": p.stat().st_size,
            })
    return {"slug": item.built_app_slug, "files": files}


@router.get("/{task_id}/files/{file_path:path}")
async def read_file(task_id: UUID, file_path: str, user: AdminUser = Depends(current_admin)):
    item = await _get_build_task(task_id)
    app_dir = Path(WORKSPACE) / "apps" / item.built_app_slug
    target = (app_dir / file_path).resolve()
    if not str(target).startswith(str(app_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.stat().st_size > 500_000:
        raise HTTPException(status_code=413, detail="File too large to preview")
    return {"path": file_path, "content": target.read_text(errors="replace")}


@router.post("/{task_id}/preview/start")
async def preview_start(task_id: UUID, user: AdminUser = Depends(current_admin)):
    item = await _get_build_task(task_id)
    try:
        port = await start_preview(item.built_app_slug)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "started", "port": port, "slug": item.built_app_slug}


@router.post("/{task_id}/preview/stop")
async def preview_stop(task_id: UUID, user: AdminUser = Depends(current_admin)):
    await stop_preview()
    return {"status": "stopped"}


@router.get("/{task_id}/preview/status")
async def preview_status(task_id: UUID, user: AdminUser = Depends(current_admin)):
    status = get_status()
    return status or {"running": False}
