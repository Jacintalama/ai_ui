# Cron Job MCP Server — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable AI in Open WebUI to create, manage, and delete cron jobs that trigger n8n workflows on a schedule.

**Architecture:** Extend the webhook-handler's existing APScheduler with CRUD REST endpoints and guardrails (1-min minimum, 10-job max, 24h auto-expiry). Create a new `mcp-scheduler` container that wraps those endpoints as MCP tools. Register in mcp-proxy so the AI can manage cron jobs from chat.

**Tech Stack:** Python, FastAPI, APScheduler, httpx, mcpo, Docker

---

### Task 1: Extend webhook-handler scheduler with CRUD and guardrails

**Files:**
- Modify: `webhook-handler/scheduler.py`
- Modify: `webhook-handler/config.py`

**Step 1: Add scheduler settings to config.py**

Add these fields to the `Settings` class in `webhook-handler/config.py` after line 49 (`report_slack_channel`):

```python
    # Scheduler guardrails
    scheduler_min_interval_minutes: int = 1
    scheduler_max_user_jobs: int = 10
    scheduler_default_expiry_hours: int = 24
```

**Step 2: Add CRUD functions and guardrails to scheduler.py**

Add the following to `webhook-handler/scheduler.py`. This adds:
- An in-memory `_user_jobs` dict to track user-created jobs (separate from default jobs)
- `create_user_cron_job()` with guardrail validation
- `delete_user_cron_job()` to remove jobs
- `update_user_cron_job()` to modify schedule or make permanent
- `get_user_jobs()` to list user-created jobs with metadata
- `_cleanup_expired_jobs()` that runs hourly to remove expired jobs
- `_validate_cron_interval()` to enforce minimum interval
- `_trigger_n8n_workflow()` the async function that APScheduler calls

Add these imports at the top of `scheduler.py`:

```python
from datetime import datetime, timezone, timedelta
import json
```

Add below the existing `register_default_jobs` function:

```python
# ---------------------------------------------------------------------------
# User-created cron jobs (with guardrails)
# ---------------------------------------------------------------------------

# In-memory store for user-created job metadata
# Key: job_id, Value: dict with cron_expression, workflow_id, etc.
_user_jobs: dict[str, dict] = {}

DEFAULT_JOB_IDS = {"daily_health_report", "hourly_n8n_check", "_cleanup_expired_jobs"}


def _validate_cron_interval(cron_expression: str, min_minutes: int) -> bool:
    """Check that a cron expression doesn't fire more often than min_minutes."""
    parts = cron_expression.split()
    if len(parts) != 5:
        return False
    minute, hour, day, month, dow = parts

    # "every N minutes" pattern: */N * * * *
    if minute.startswith("*/") and hour == "*" and day == "*":
        try:
            interval = int(minute.split("/")[1])
            return interval >= min_minutes
        except (ValueError, IndexError):
            return False

    # "every minute" pattern: * * * * *
    if minute == "*" and hour == "*" and day == "*":
        return 1 >= min_minutes

    # Specific minute + wildcard hour (e.g., "0 * * * *" = every hour) → always OK
    # Specific minute + specific hour → daily or less frequent → always OK
    return True


async def _trigger_n8n_workflow(
    job_id: str,
    workflow_id: str,
    trigger_method: str,
    webhook_path: str = "",
    payload: dict = None,
    n8n_url: str = "",
    n8n_api_key: str = "",
):
    """Async function called by APScheduler to trigger an n8n workflow."""
    logger.info(f"Cron job '{job_id}' firing → n8n workflow {workflow_id} ({trigger_method})")

    headers = {"Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            if trigger_method == "webhook" and webhook_path:
                url = f"{n8n_url}/webhook/{webhook_path}"
                resp = await client.post(url, json=payload or {}, headers=headers)
            else:
                url = f"{n8n_url}/api/v1/workflows/{workflow_id}/execute"
                headers["X-N8N-API-KEY"] = n8n_api_key
                resp = await client.post(url, json={"data": payload or {}}, headers=headers)

            logger.info(f"Cron job '{job_id}' → n8n response: {resp.status_code}")

            # Update last_run in metadata
            if job_id in _user_jobs:
                _user_jobs[job_id]["last_run"] = datetime.now(timezone.utc).isoformat()
                _user_jobs[job_id]["last_status"] = "success" if resp.status_code < 400 else f"error:{resp.status_code}"

    except Exception as e:
        logger.error(f"Cron job '{job_id}' failed: {e}")
        if job_id in _user_jobs:
            _user_jobs[job_id]["last_run"] = datetime.now(timezone.utc).isoformat()
            _user_jobs[job_id]["last_status"] = f"error:{e}"


def create_user_cron_job(
    job_id: str,
    cron_expression: str,
    workflow_id: str,
    trigger_method: str = "api",
    webhook_path: str = "",
    payload: dict = None,
    description: str = "",
    permanent: bool = False,
    n8n_url: str = "",
    n8n_api_key: str = "",
    min_interval_minutes: int = 1,
    max_user_jobs: int = 10,
    default_expiry_hours: int = 24,
) -> dict:
    """
    Create a user-defined cron job that triggers an n8n workflow.

    Returns dict with success status and job details.
    """
    if not scheduler:
        return {"success": False, "error": "Scheduler not initialized"}

    # Validate cron expression format
    parts = cron_expression.split()
    if len(parts) != 5:
        return {"success": False, "error": f"Invalid cron expression (need 5 parts): {cron_expression}"}

    # Guardrail: minimum interval
    if not _validate_cron_interval(cron_expression, min_interval_minutes):
        return {
            "success": False,
            "error": f"Schedule too frequent. Minimum interval is {min_interval_minutes} minute(s).",
        }

    # Guardrail: max user jobs
    if job_id not in _user_jobs and len(_user_jobs) >= max_user_jobs:
        return {
            "success": False,
            "error": f"Maximum {max_user_jobs} user cron jobs allowed. Delete one first.",
        }

    # Guardrail: don't overwrite default jobs
    if job_id in DEFAULT_JOB_IDS:
        return {"success": False, "error": f"Cannot overwrite system job '{job_id}'"}

    # Calculate expiry
    now = datetime.now(timezone.utc)
    expires_at = None if permanent else (now + timedelta(hours=default_expiry_hours)).isoformat()

    # Register with APScheduler
    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )

    scheduler.add_job(
        _trigger_n8n_workflow,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        kwargs={
            "job_id": job_id,
            "workflow_id": workflow_id,
            "trigger_method": trigger_method,
            "webhook_path": webhook_path,
            "payload": payload or {},
            "n8n_url": n8n_url,
            "n8n_api_key": n8n_api_key,
        },
    )

    # Store metadata
    _user_jobs[job_id] = {
        "job_id": job_id,
        "cron_expression": cron_expression,
        "workflow_id": workflow_id,
        "trigger_method": trigger_method,
        "webhook_path": webhook_path,
        "payload": payload or {},
        "description": description,
        "permanent": permanent,
        "expires_at": expires_at,
        "created_at": now.isoformat(),
        "last_run": None,
        "last_status": None,
    }

    # Get next run time from APScheduler
    ap_job = scheduler.get_job(job_id)
    next_run = str(ap_job.next_run_time) if ap_job else "unknown"

    logger.info(f"Created user cron job '{job_id}': {cron_expression} → workflow {workflow_id}")

    return {
        "success": True,
        "job_id": job_id,
        "cron_expression": cron_expression,
        "workflow_id": workflow_id,
        "next_run": next_run,
        "permanent": permanent,
        "expires_at": expires_at,
        "description": description,
    }


def delete_user_cron_job(job_id: str) -> dict:
    """Delete a user-created cron job."""
    if not scheduler:
        return {"success": False, "error": "Scheduler not initialized"}

    if job_id in DEFAULT_JOB_IDS:
        return {"success": False, "error": f"Cannot delete system job '{job_id}'"}

    if job_id not in _user_jobs:
        return {"success": False, "error": f"Job '{job_id}' not found"}

    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass  # Job may already be removed from APScheduler

    del _user_jobs[job_id]
    logger.info(f"Deleted user cron job '{job_id}'")

    return {"success": True, "message": f"Job '{job_id}' deleted"}


def update_user_cron_job(
    job_id: str,
    cron_expression: str = None,
    permanent: bool = None,
    min_interval_minutes: int = 1,
    default_expiry_hours: int = 24,
) -> dict:
    """Update a user-created cron job's schedule or permanence."""
    if not scheduler:
        return {"success": False, "error": "Scheduler not initialized"}

    if job_id not in _user_jobs:
        return {"success": False, "error": f"Job '{job_id}' not found"}

    meta = _user_jobs[job_id]

    # Update permanent flag
    if permanent is not None:
        meta["permanent"] = permanent
        if permanent:
            meta["expires_at"] = None
        else:
            meta["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(hours=default_expiry_hours)
            ).isoformat()

    # Update schedule
    if cron_expression:
        parts = cron_expression.split()
        if len(parts) != 5:
            return {"success": False, "error": f"Invalid cron expression: {cron_expression}"}

        if not _validate_cron_interval(cron_expression, min_interval_minutes):
            return {"success": False, "error": f"Minimum interval is {min_interval_minutes} minute(s)."}

        trigger = CronTrigger(
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4],
        )
        scheduler.reschedule_job(job_id, trigger=trigger)
        meta["cron_expression"] = cron_expression

    ap_job = scheduler.get_job(job_id)
    next_run = str(ap_job.next_run_time) if ap_job else "unknown"

    return {"success": True, "job_id": job_id, "next_run": next_run, **meta}


def get_user_jobs() -> list[dict]:
    """Get all user-created cron jobs with metadata."""
    jobs = []
    for job_id, meta in _user_jobs.items():
        ap_job = scheduler.get_job(job_id) if scheduler else None
        jobs.append({
            **meta,
            "next_run": str(ap_job.next_run_time) if ap_job else "removed",
        })
    return jobs


async def _cleanup_expired_jobs():
    """Remove expired non-permanent jobs. Runs hourly."""
    now = datetime.now(timezone.utc)
    expired = []
    for job_id, meta in _user_jobs.items():
        if meta.get("expires_at") and not meta.get("permanent"):
            expires_at = datetime.fromisoformat(meta["expires_at"])
            if now >= expires_at:
                expired.append(job_id)

    for job_id in expired:
        logger.info(f"Auto-expiring cron job '{job_id}'")
        delete_user_cron_job(job_id)

    if expired:
        logger.info(f"Cleaned up {len(expired)} expired cron job(s)")
```

**Step 3: Register the cleanup job in register_default_jobs**

In `register_default_jobs()`, add the cleanup job after the hourly n8n check (after line 250):

```python
    # Hourly cleanup of expired user cron jobs
    add_cron_job(
        func=_cleanup_expired_jobs,
        job_id="_cleanup_expired_jobs",
        cron_expression="30 * * * *",
    )
```

**Step 4: Export new functions from scheduler.py**

Update the imports in `webhook-handler/main.py` line 23-27 to include the new functions:

```python
from scheduler import (
    init_scheduler, start_scheduler, shutdown_scheduler,
    list_jobs, trigger_job, register_default_jobs,
    daily_health_report, hourly_n8n_workflow_check,
    create_user_cron_job, delete_user_cron_job,
    update_user_cron_job, get_user_jobs,
)
```

**Step 5: Commit**

```bash
git add webhook-handler/scheduler.py webhook-handler/config.py webhook-handler/main.py
git commit -m "feat(scheduler): add CRUD functions and guardrails for user cron jobs"
```

---

### Task 2: Add REST API routes for cron job management

**Files:**
- Modify: `webhook-handler/main.py`

**Step 1: Add Pydantic request models**

Add these imports at the top of `main.py`:

```python
from pydantic import BaseModel
```

Add request models before the `lifespan` function:

```python
class CreateCronJobRequest(BaseModel):
    job_id: str
    cron_expression: str
    workflow_id: str
    trigger_method: str = "api"  # "api" or "webhook"
    webhook_path: str = ""
    payload: dict = {}
    description: str = ""
    permanent: bool = False


class UpdateCronJobRequest(BaseModel):
    cron_expression: str = None
    permanent: bool = None
```

**Step 2: Add the CRUD endpoints**

Add these routes after the existing `/scheduler/n8n-check` endpoint (after line 522):

```python
@app.post("/scheduler/jobs")
async def create_cron_job_endpoint(req: CreateCronJobRequest):
    """Create a new user cron job that triggers an n8n workflow on schedule."""
    result = create_user_cron_job(
        job_id=req.job_id,
        cron_expression=req.cron_expression,
        workflow_id=req.workflow_id,
        trigger_method=req.trigger_method,
        webhook_path=req.webhook_path,
        payload=req.payload,
        description=req.description,
        permanent=req.permanent,
        n8n_url=settings.n8n_url,
        n8n_api_key=settings.n8n_api_key,
        min_interval_minutes=settings.scheduler_min_interval_minutes,
        max_user_jobs=settings.scheduler_max_user_jobs,
        default_expiry_hours=settings.scheduler_default_expiry_hours,
    )
    if result.get("success"):
        return JSONResponse(content=result, status_code=201)
    else:
        return JSONResponse(content=result, status_code=400)


@app.delete("/scheduler/jobs/{job_id}")
async def delete_cron_job_endpoint(job_id: str):
    """Delete a user-created cron job."""
    result = delete_user_cron_job(job_id)
    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=404)


@app.patch("/scheduler/jobs/{job_id}")
async def update_cron_job_endpoint(job_id: str, req: UpdateCronJobRequest):
    """Update a user cron job's schedule or permanence."""
    result = update_user_cron_job(
        job_id=job_id,
        cron_expression=req.cron_expression,
        permanent=req.permanent,
        min_interval_minutes=settings.scheduler_min_interval_minutes,
        default_expiry_hours=settings.scheduler_default_expiry_hours,
    )
    if result.get("success"):
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=400)


@app.get("/scheduler/user-jobs")
async def get_user_jobs_endpoint():
    """List all user-created cron jobs with metadata (separate from system jobs)."""
    jobs = get_user_jobs()
    return {"jobs": jobs, "count": len(jobs)}
```

**Step 3: Commit**

```bash
git add webhook-handler/main.py
git commit -m "feat(scheduler): add REST endpoints for cron job CRUD"
```

---

### Task 3: Create the mcp-scheduler MCP server

**Files:**
- Create: `mcp-servers/scheduler/main.py`
- Create: `mcp-servers/scheduler/Dockerfile`
- Create: `mcp-servers/scheduler/requirements.txt`

**Step 1: Create requirements.txt**

```
fastapi>=0.104.0
uvicorn>=0.24.0
httpx>=0.25.0
```

**Step 2: Create the FastAPI app (main.py)**

This is the MCP tool server. It exposes 4 tools as OpenAPI endpoints that mcpo wraps for mcp-proxy. It includes human-readable schedule parsing.

```python
"""Scheduler MCP Server — manage cron jobs that trigger n8n workflows."""
import os
import re
import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional

app = FastAPI(
    title="Scheduler MCP",
    description="Create and manage cron jobs that trigger n8n workflows on a schedule.",
    version="1.0.0",
)

WEBHOOK_HANDLER_URL = os.getenv("WEBHOOK_HANDLER_URL", "http://webhook-handler:8001")


# ---------------------------------------------------------------------------
# Human-readable schedule → cron expression
# ---------------------------------------------------------------------------

SCHEDULE_PATTERNS = [
    (r"every (\d+) minutes?", lambda m: f"*/{m.group(1)} * * * *"),
    (r"every (\d+) hours?", lambda m: f"0 */{m.group(1)} * * *"),
    (r"every hour", lambda m: "0 * * * *"),
    (r"every minute", lambda m: "* * * * *"),
    (r"every day at (\d{1,2})\s*(am|pm)?", _parse_daily),
    (r"every (monday|tuesday|wednesday|thursday|friday|saturday|sunday) at (\d{1,2})\s*(am|pm)?", _parse_weekly),
    (r"daily at (\d{1,2}):?(\d{2})?\s*(am|pm)?", _parse_daily_full),
]

DAY_MAP = {
    "monday": "1", "tuesday": "2", "wednesday": "3", "thursday": "4",
    "friday": "5", "saturday": "6", "sunday": "0",
}


def _parse_daily(m):
    hour = int(m.group(1))
    ampm = m.group(2)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return f"0 {hour} * * *"


def _parse_weekly(m):
    day = DAY_MAP.get(m.group(1).lower(), "*")
    hour = int(m.group(2))
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return f"0 {hour} * * {day}"


def _parse_daily_full(m):
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return f"{minute} {hour} * * *"


def parse_schedule(schedule: str) -> str:
    """Convert human-readable schedule to cron expression, or pass through if already cron."""
    schedule = schedule.strip().lower()

    # Already a cron expression (5 parts with */digits or digits)
    if re.match(r"^[\d\*/,\-]+(\s+[\d\*/,\-]+){4}$", schedule):
        return schedule

    for pattern, handler in SCHEDULE_PATTERNS:
        match = re.match(pattern, schedule, re.IGNORECASE)
        if match:
            return handler(match)

    raise ValueError(f"Cannot parse schedule: '{schedule}'. Use a cron expression (e.g., '*/5 * * * *') or natural language (e.g., 'every 30 minutes').")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateCronJobInput(BaseModel):
    """Create a cron job that triggers an n8n workflow on a schedule."""
    schedule: str = Field(
        description="When to run. Human-readable (e.g., 'every 30 minutes', 'every day at 8pm', 'every monday at 9am') or cron expression (e.g., '*/30 * * * *')."
    )
    workflow_id: str = Field(description="The n8n workflow ID to trigger.")
    description: str = Field(default="", description="Human-readable description of what this job does.")
    permanent: bool = Field(default=False, description="If false, job auto-expires after 24 hours. Set true for production jobs.")
    trigger_method: str = Field(default="api", description="How to trigger the workflow: 'api' (by workflow ID) or 'webhook' (by webhook path).")
    webhook_path: str = Field(default="", description="Webhook path in n8n (only if trigger_method='webhook').")
    payload: dict = Field(default={}, description="Optional JSON payload to send to the workflow.")


class DeleteCronJobInput(BaseModel):
    """Delete an existing cron job."""
    job_id: str = Field(description="The ID of the cron job to delete.")


class TriggerCronJobInput(BaseModel):
    """Manually trigger a cron job to run immediately."""
    job_id: str = Field(description="The ID of the cron job to trigger now.")


# ---------------------------------------------------------------------------
# Tool endpoints
# ---------------------------------------------------------------------------

@app.post("/create_cron_job", operation_id="create_cron_job", summary="Create a scheduled cron job that triggers an n8n workflow")
async def create_cron_job(input: CreateCronJobInput):
    """Create a new cron job that triggers an n8n workflow on a time-based schedule.

    Supports human-readable schedules like 'every 30 minutes', 'every day at 8pm',
    'every monday at 9am', or standard cron expressions like '*/5 * * * *'.

    Safety guardrails: minimum 1-minute interval, max 10 active jobs,
    auto-expires after 24 hours unless marked permanent.
    """
    # Parse schedule to cron expression
    try:
        cron_expression = parse_schedule(input.schedule)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Generate a job ID from description or workflow ID
    job_id = re.sub(r"[^a-z0-9]+", "-", (input.description or f"wf-{input.workflow_id}").lower()).strip("-")[:50]

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{WEBHOOK_HANDLER_URL}/scheduler/jobs",
            json={
                "job_id": job_id,
                "cron_expression": cron_expression,
                "workflow_id": input.workflow_id,
                "trigger_method": input.trigger_method,
                "webhook_path": input.webhook_path,
                "payload": input.payload,
                "description": input.description,
                "permanent": input.permanent,
            },
        )
        return resp.json()


@app.get("/list_cron_jobs", operation_id="list_cron_jobs", summary="List all scheduled cron jobs")
async def list_cron_jobs():
    """List all cron jobs including system jobs and user-created jobs.

    Shows job ID, schedule, next run time, workflow ID, and expiry status.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Get both system jobs and user jobs
        system_resp = await client.get(f"{WEBHOOK_HANDLER_URL}/scheduler/jobs")
        user_resp = await client.get(f"{WEBHOOK_HANDLER_URL}/scheduler/user-jobs")

        system_jobs = system_resp.json().get("jobs", [])
        user_jobs = user_resp.json().get("jobs", [])

        return {
            "system_jobs": system_jobs,
            "user_jobs": user_jobs,
            "total_system": len(system_jobs),
            "total_user": len(user_jobs),
        }


@app.post("/delete_cron_job", operation_id="delete_cron_job", summary="Delete a cron job")
async def delete_cron_job(input: DeleteCronJobInput):
    """Delete a user-created cron job. Cannot delete system jobs (health report, n8n check)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.delete(f"{WEBHOOK_HANDLER_URL}/scheduler/jobs/{input.job_id}")
        return resp.json()


@app.post("/trigger_cron_job", operation_id="trigger_cron_job", summary="Manually trigger a cron job now")
async def trigger_cron_job(input: TriggerCronJobInput):
    """Manually run a cron job immediately, without waiting for the next scheduled time."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{WEBHOOK_HANDLER_URL}/scheduler/jobs/{input.job_id}/trigger")
        return resp.json()


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mcp-scheduler"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Step 3: Create the Dockerfile**

```dockerfile
# mcp-servers/scheduler/Dockerfile
# Scheduler MCP Server — wraps webhook-handler scheduler API as MCP tools
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt mcpo

COPY main.py .

EXPOSE 8000

CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"${MCP_API_KEY:-mcp-secret-key}\" -- uvicorn main:app --host 127.0.0.1 --port 8001"]
```

**Step 4: Commit**

```bash
git add mcp-servers/scheduler/
git commit -m "feat: add scheduler MCP server with 4 tools (create, list, delete, trigger)"
```

---

### Task 4: Register in docker-compose and mcp-proxy

**Files:**
- Modify: `docker-compose.unified.yml`
- Modify: `mcp-proxy/tenants.py`
- Modify: `mcp-proxy/config/mcp-servers.json`

**Step 1: Add mcp-scheduler service to docker-compose.unified.yml**

Add after the `mcp-n8n` service block (after line 462):

```yaml
  # Scheduler MCP - Cron job management from chat (4 tools)
  mcp-scheduler:
    build: ./mcp-servers/scheduler
    container_name: mcp-scheduler
    restart: unless-stopped
    environment:
      - WEBHOOK_HANDLER_URL=http://webhook-handler:8086
      - MCP_API_KEY=${MCP_API_KEY:-mcp-secret-key}
    networks:
      - backend
    depends_on:
      - webhook-handler
    deploy:
      resources:
        limits:
          memory: 256M
        reservations:
          memory: 128M
```

**Step 2: Add MCP_SCHEDULER_URL to mcp-proxy environment in docker-compose**

In the `mcp-proxy` service environment section (after `MCP_N8N_URL` around line 186):

```yaml
      - MCP_SCHEDULER_URL=http://mcp-scheduler:8000
```

**Step 3: Register scheduler in mcp-proxy/tenants.py**

Add the URL variable after `MCP_N8N_URL` (after line 562):

```python
MCP_SCHEDULER_URL = os.getenv("MCP_SCHEDULER_URL", "http://mcp-scheduler:8000")
```

Add the server config in `LOCAL_SERVERS` dict after the `"n8n"` entry (after line 632):

```python
    "scheduler": MCPServerConfig(
        server_id="scheduler",
        display_name="Scheduler",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_SCHEDULER_URL,
        auth_type="bearer",
        api_key_env="MCP_API_KEY",
        description="Create and manage cron jobs that trigger n8n workflows on a schedule (4 tools)",
        enabled=True,
    ),
```

**Step 4: Add scheduler to mcp-servers.json**

Add after the `"n8n"` entry in `mcp-proxy/config/mcp-servers.json`:

```json
    {
      "id": "scheduler",
      "name": "Scheduler MCP",
      "url": "http://mcp-proxy:8000/scheduler",
      "type": "openapi",
      "description": "Create and manage cron jobs that trigger n8n workflows on a schedule",
      "tier": "local",
      "groups": ["MCP-Admin"],
      "api_key_env": null
    }
```

**Step 5: Commit**

```bash
git add docker-compose.unified.yml mcp-proxy/tenants.py mcp-proxy/config/mcp-servers.json
git commit -m "feat: register mcp-scheduler in docker-compose and mcp-proxy"
```

---

### Task 5: Deploy and test on server

**Files:**
- No code changes — deployment steps only

**Step 1: Copy changed files to server**

```bash
scp mcp-servers/scheduler/main.py root@46.224.193.25:/root/proxy-server/mcp-servers/scheduler/main.py
scp mcp-servers/scheduler/Dockerfile root@46.224.193.25:/root/proxy-server/mcp-servers/scheduler/Dockerfile
scp mcp-servers/scheduler/requirements.txt root@46.224.193.25:/root/proxy-server/mcp-servers/scheduler/requirements.txt
scp webhook-handler/scheduler.py root@46.224.193.25:/root/proxy-server/webhook-handler/scheduler.py
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
scp mcp-proxy/tenants.py root@46.224.193.25:/root/proxy-server/mcp-proxy/tenants.py
scp mcp-proxy/config/mcp-servers.json root@46.224.193.25:/root/proxy-server/mcp-proxy/config/mcp-servers.json
```

**Step 2: Create scheduler directory on server and build**

```bash
ssh root@46.224.193.25 "mkdir -p /root/proxy-server/mcp-servers/scheduler"
# Re-copy files after mkdir
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache mcp-scheduler webhook-handler mcp-proxy"
```

**Step 3: Restart affected services**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d mcp-scheduler webhook-handler mcp-proxy"
```

**Step 4: Verify containers are running**

```bash
ssh root@46.224.193.25 "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'scheduler|webhook|mcp-proxy'"
```

Expected: mcp-scheduler, webhook-handler, mcp-proxy all show "Up"

**Step 5: Test the webhook-handler API directly**

```bash
# List jobs (should show 3 system jobs)
ssh root@46.224.193.25 "curl -s http://localhost:8086/scheduler/jobs | python3 -m json.tool"

# Create a test job
ssh root@46.224.193.25 'curl -s -X POST http://localhost:8086/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '"'"'{"job_id":"test-cron","cron_expression":"* * * * *","workflow_id":"test","description":"Test every minute","permanent":false}'"'"' | python3 -m json.tool'

# List user jobs
ssh root@46.224.193.25 "curl -s http://localhost:8086/scheduler/user-jobs | python3 -m json.tool"

# Delete test job
ssh root@46.224.193.25 'curl -s -X DELETE http://localhost:8086/scheduler/jobs/test-cron | python3 -m json.tool'
```

**Step 6: Test the MCP server**

```bash
ssh root@46.224.193.25 "curl -s http://localhost:$(docker port mcp-scheduler 8000 | cut -d: -f2)/health"
```

---

### Task 6: Create test n8n workflow and validate end-to-end from chat

**Step 1: Create a "Cron Test" workflow on n8n**

From Open WebUI chat with gpt-5, ask the AI:
> "Use n8n_create_workflow to create a simple test workflow called 'Cron Test - Hello World'. It should have a Webhook trigger node and a Set node that outputs: message = 'Cron triggered successfully at [current timestamp]'. Use webhook path 'cron-test'."

**Step 2: Test the cron job from chat**

In a fresh Open WebUI chat:
> "Create a cron job that runs every minute to trigger the 'Cron Test - Hello World' workflow."

The AI should call `create_cron_job` with schedule "every minute" and the workflow ID.

**Step 3: Verify in n8n**

Open n8n UI → Executions tab. Within 2 minutes, you should see executions of the "Cron Test" workflow appearing.

**Step 4: Clean up the test**

In Open WebUI chat:
> "List all cron jobs"

Then:
> "Delete the cron test job"

**Step 5: Commit everything**

```bash
git add -A
git commit -m "feat: cron job MCP server - create/manage scheduled n8n workflows from chat"
```

---

## Summary of all changes

| # | Task | Files | Description |
|---|------|-------|-------------|
| 1 | Scheduler CRUD | `webhook-handler/scheduler.py`, `config.py` | Add create/delete/update/list + guardrails |
| 2 | REST API | `webhook-handler/main.py` | POST/DELETE/PATCH/GET endpoints |
| 3 | MCP Server | `mcp-servers/scheduler/*` (3 new files) | FastAPI app with 4 tools + Dockerfile |
| 4 | Integration | `docker-compose.unified.yml`, `tenants.py`, `mcp-servers.json` | Register in stack |
| 5 | Deploy | Server commands | Build, restart, verify |
| 6 | E2E Test | Open WebUI chat | Create test workflow, schedule it, verify |
