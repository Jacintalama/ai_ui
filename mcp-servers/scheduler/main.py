"""Scheduler MCP Server — manage cron jobs that trigger n8n workflows."""
import os
import re
import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="Scheduler MCP",
    description="Create and manage cron jobs that trigger n8n workflows on a schedule.",
    version="1.0.0",
)

WEBHOOK_HANDLER_URL = os.getenv("WEBHOOK_HANDLER_URL", "http://webhook-handler:8086")


# ---------------------------------------------------------------------------
# Human-readable schedule → cron expression
# ---------------------------------------------------------------------------

DAY_MAP = {
    "monday": "1", "tuesday": "2", "wednesday": "3", "thursday": "4",
    "friday": "5", "saturday": "6", "sunday": "0",
}


def _parse_hour(hour_str: str, ampm: str | None) -> int:
    """Convert hour + optional am/pm to 24-hour int."""
    hour = int(hour_str)
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    return hour


def parse_schedule(schedule: str) -> str:
    """Convert human-readable schedule to cron expression, or pass through if already cron."""
    s = schedule.strip()

    # Already a cron expression (5 space-separated fields)
    if re.match(r"^[\d\*/,\-]+(\s+[\d\*/,\-]+){4}$", s):
        return s

    low = s.lower()

    # "every N minutes"
    m = re.match(r"every (\d+) minutes?", low)
    if m:
        return f"*/{m.group(1)} * * * *"

    # "every N hours"
    m = re.match(r"every (\d+) hours?", low)
    if m:
        return f"0 */{m.group(1)} * * *"

    # "every hour"
    if re.match(r"every hour", low):
        return "0 * * * *"

    # "every minute"
    if re.match(r"every minute", low):
        return "* * * * *"

    # "every day at 8pm" / "daily at 8pm" / "every day at 20:30"
    m = re.match(r"(?:every day|daily) at (\d{1,2}):?(\d{2})?\s*(am|pm)?", low)
    if m:
        hour = _parse_hour(m.group(1), m.group(3))
        minute = int(m.group(2)) if m.group(2) else 0
        return f"{minute} {hour} * * *"

    # "every monday at 9am"
    m = re.match(
        r"every (monday|tuesday|wednesday|thursday|friday|saturday|sunday) at (\d{1,2}):?(\d{2})?\s*(am|pm)?",
        low,
    )
    if m:
        day = DAY_MAP.get(m.group(1), "*")
        hour = _parse_hour(m.group(2), m.group(4))
        minute = int(m.group(3)) if m.group(3) else 0
        return f"{minute} {hour} * * {day}"

    raise ValueError(
        f"Cannot parse schedule: '{schedule}'. "
        "Use cron (e.g., '*/5 * * * *') or natural language "
        "(e.g., 'every 30 minutes', 'every day at 8pm', 'every monday at 9am')."
    )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateCronJobInput(BaseModel):
    """Create a cron job that triggers an n8n workflow on a schedule."""
    schedule: str = Field(
        description=(
            "When to run. Human-readable ('every 30 minutes', 'every day at 8pm', "
            "'every monday at 9am') or cron expression ('*/30 * * * *')."
        )
    )
    workflow_id: str = Field(description="The n8n workflow ID to trigger.")
    description: str = Field(default="", description="Human-readable description of what this job does.")
    permanent: bool = Field(
        default=False,
        description="If false, job auto-expires after 24 hours. Set true for production jobs.",
    )
    trigger_method: str = Field(
        default="api",
        description="How to trigger the workflow: 'api' (by workflow ID) or 'webhook' (by webhook path).",
    )
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

@app.post(
    "/create_cron_job",
    operation_id="create_cron_job",
    summary="Create a scheduled cron job that triggers an n8n workflow",
)
async def create_cron_job(input: CreateCronJobInput):
    """Create a new cron job that triggers an n8n workflow on a time-based schedule.

    Supports human-readable schedules like 'every 30 minutes', 'every day at 8pm',
    'every monday at 9am', or standard cron expressions like '*/5 * * * *'.

    Safety guardrails: minimum 1-minute interval, max 10 active jobs,
    auto-expires after 24 hours unless marked permanent.
    """
    try:
        cron_expression = parse_schedule(input.schedule)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Generate a slug-style job ID from description or workflow ID
    source = input.description or f"wf-{input.workflow_id}"
    job_id = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:50]

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


@app.post(
    "/list_cron_jobs",
    operation_id="list_cron_jobs",
    summary="List all scheduled cron jobs",
)
async def list_cron_jobs():
    """List all cron jobs including system jobs and user-created jobs.

    Shows job ID, schedule, next run time, workflow ID, and expiry status.
    No input required — just call this tool to see all jobs.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        system_resp = await client.get(f"{WEBHOOK_HANDLER_URL}/scheduler/jobs")
        user_resp = await client.get(f"{WEBHOOK_HANDLER_URL}/scheduler/user-jobs")

        return {
            "system_jobs": system_resp.json().get("jobs", []),
            "user_jobs": user_resp.json().get("jobs", []),
            "total_system": system_resp.json().get("count", 0),
            "total_user": user_resp.json().get("count", 0),
        }


@app.post(
    "/delete_cron_job",
    operation_id="delete_cron_job",
    summary="Delete a cron job",
)
async def delete_cron_job(input: DeleteCronJobInput):
    """Delete a user-created cron job. Cannot delete system jobs (health report, n8n check)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.delete(f"{WEBHOOK_HANDLER_URL}/scheduler/jobs/{input.job_id}")
        return resp.json()


@app.post(
    "/trigger_cron_job",
    operation_id="trigger_cron_job",
    summary="Manually trigger a cron job now",
)
async def trigger_cron_job(input: TriggerCronJobInput):
    """Manually run a cron job immediately, without waiting for the next scheduled time."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{WEBHOOK_HANDLER_URL}/scheduler/jobs/{input.job_id}/trigger")
        return resp.json()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "mcp-scheduler"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
