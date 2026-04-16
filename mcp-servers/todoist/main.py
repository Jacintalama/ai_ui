"""Todoist web app — proxy to Todoist REST API v2."""
import logging
import os

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("todoist")

TODOIST_API_TOKEN = os.environ.get("TODOIST_API_TOKEN", "")
TODOIST_API_BASE = "https://api.todoist.com/rest/v2"


def _get_token(x_todoist_token: str = "") -> str:
    """Resolve API token: per-request header overrides env var."""
    return x_todoist_token or TODOIST_API_TOKEN


def _headers(token: str) -> dict[str, str]:
    if not token:
        raise HTTPException(status_code=503, detail="TODOIST_API_TOKEN not configured")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


app = FastAPI(title="Todoist Service", version="0.1.0")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/api/todoist/projects")
async def list_projects(x_todoist_token: str = Header(default="")):
    token = _get_token(x_todoist_token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{TODOIST_API_BASE}/projects", headers=_headers(token))
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class CreateTaskBody(BaseModel):
    content: str
    description: str = ""
    project_id: str | None = None
    due_string: str | None = None
    priority: int = 1  # 1=normal … 4=urgent


class UpdateTaskBody(BaseModel):
    content: str | None = None
    description: str | None = None
    due_string: str | None = None
    priority: int | None = None


@app.get("/api/todoist/tasks")
async def list_tasks(
    project_id: str | None = None,
    filter: str | None = None,
    x_todoist_token: str = Header(default=""),
):
    token = _get_token(x_todoist_token)
    params: dict[str, str] = {}
    if project_id:
        params["project_id"] = project_id
    if filter:
        params["filter"] = filter
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{TODOIST_API_BASE}/tasks",
                headers=_headers(token),
                params=params,
            )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


@app.post("/api/todoist/tasks", status_code=200)
async def create_task(body: CreateTaskBody, x_todoist_token: str = Header(default="")):
    token = _get_token(x_todoist_token)
    payload: dict = {"content": body.content, "priority": body.priority}
    if body.description:
        payload["description"] = body.description
    if body.project_id:
        payload["project_id"] = body.project_id
    if body.due_string:
        payload["due_string"] = body.due_string
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{TODOIST_API_BASE}/tasks",
                headers=_headers(token),
                json=payload,
            )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


@app.post("/api/todoist/tasks/{task_id}/close", status_code=204)
async def close_task(task_id: str, x_todoist_token: str = Header(default="")):
    token = _get_token(x_todoist_token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{TODOIST_API_BASE}/tasks/{task_id}/close",
                headers=_headers(token),
            )
        r.raise_for_status()
        return JSONResponse(status_code=204, content=None)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


@app.post("/api/todoist/tasks/{task_id}/reopen", status_code=204)
async def reopen_task(task_id: str, x_todoist_token: str = Header(default="")):
    token = _get_token(x_todoist_token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{TODOIST_API_BASE}/tasks/{task_id}/reopen",
                headers=_headers(token),
            )
        r.raise_for_status()
        return JSONResponse(status_code=204, content=None)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


@app.patch("/api/todoist/tasks/{task_id}")
async def update_task(
    task_id: str,
    body: UpdateTaskBody,
    x_todoist_token: str = Header(default=""),
):
    token = _get_token(x_todoist_token)
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{TODOIST_API_BASE}/tasks/{task_id}",
                headers=_headers(token),
                json=payload,
            )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


@app.delete("/api/todoist/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, x_todoist_token: str = Header(default="")):
    token = _get_token(x_todoist_token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.delete(
                f"{TODOIST_API_BASE}/tasks/{task_id}",
                headers=_headers(token),
            )
        r.raise_for_status()
        return JSONResponse(status_code=204, content=None)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Todoist unreachable: {exc}")


# ---------------------------------------------------------------------------
# Health + static files
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    configured = "yes" if TODOIST_API_TOKEN else "no"
    return {"status": "ok", "service": "todoist", "token_configured": configured}


app.mount("/todoist/static", StaticFiles(directory="static"), name="static")
