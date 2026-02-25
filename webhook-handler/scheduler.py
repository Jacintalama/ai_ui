"""Scheduled task manager using APScheduler."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Any
import httpx
import logging

from config import settings, get_service_endpoints

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None


def init_scheduler() -> AsyncIOScheduler:
    """Initialize and return the scheduler instance."""
    global scheduler
    scheduler = AsyncIOScheduler()
    logger.info("Scheduler initialized")
    return scheduler


def start_scheduler():
    """Start the scheduler."""
    if scheduler and not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def shutdown_scheduler():
    """Shut down the scheduler."""
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down")


def add_cron_job(
    func: Callable,
    job_id: str,
    cron_expression: str,
    **kwargs: Any
):
    """
    Add a cron-based scheduled job.

    Args:
        func: Async function to call
        job_id: Unique job identifier
        cron_expression: Cron expression (e.g., '0 8 * * *' for 8 AM daily)
        **kwargs: Additional arguments passed to func
    """
    if not scheduler:
        logger.error("Scheduler not initialized")
        return

    parts = cron_expression.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4]
        )
    else:
        logger.error(f"Invalid cron expression: {cron_expression}")
        return

    scheduler.add_job(
        func,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        kwargs=kwargs
    )
    logger.info(f"Scheduled job '{job_id}' with cron: {cron_expression}")


def list_jobs() -> list[dict]:
    """List all scheduled jobs."""
    if not scheduler:
        return []

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": getattr(job, "name", job.id),
            "next_run": str(getattr(job, "next_run_time", None)),
            "trigger": str(job.trigger),
        })
    return jobs


def trigger_job(job_id: str) -> dict:
    """
    Manually trigger a scheduled job immediately.

    Returns:
        Result dict with success status and message.
    """
    if not scheduler:
        return {"success": False, "error": "Scheduler not initialized"}

    job = scheduler.get_job(job_id)
    if not job:
        return {"success": False, "error": f"Job '{job_id}' not found"}

    # Modify the job to run now (next tick)
    job.modify(next_run_time=None)
    # APScheduler: setting next_run_time to None pauses it; instead reschedule
    # Use the scheduler's modify_job to add an immediate run
    try:
        from datetime import datetime, timezone
        scheduler.modify_job(job_id, next_run_time=datetime.now(timezone.utc))
        return {"success": True, "message": f"Job '{job_id}' triggered"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Default scheduled jobs
# ---------------------------------------------------------------------------

SERVICE_ENDPOINTS = get_service_endpoints()


async def _check_service_health(name: str, url: str, timeout: float = 10.0) -> dict:
    """Check a single service health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return {
                "service": name,
                "url": url,
                "status": "healthy" if resp.status_code < 400 else "unhealthy",
                "status_code": resp.status_code,
            }
    except Exception as e:
        return {
            "service": name,
            "url": url,
            "status": "unreachable",
            "error": str(e),
        }


async def daily_health_report(slack_client=None, slack_channel: str = ""):
    """
    Daily health check of all services.

    Runs at noon every day. Checks every registered service endpoint,
    logs the results, and posts to Slack if configured.
    """
    logger.info("=== Daily Health Report ===")
    results = []
    for name, url in SERVICE_ENDPOINTS.items():
        result = await _check_service_health(name, url)
        results.append(result)
        status_emoji = "OK" if result["status"] == "healthy" else "FAIL"
        logger.info(f"  [{status_emoji}] {name}: {result['status']} ({url})")

    healthy = sum(1 for r in results if r["status"] == "healthy")
    total = len(results)
    logger.info(f"=== Health Report: {healthy}/{total} services healthy ===")

    # Post to Slack if configured
    if slack_client and slack_channel:
        lines = [f"*Service Health Report* ({healthy}/{total} healthy)\n"]
        for r in results:
            emoji = "white_check_mark" if r["status"] == "healthy" else "x"
            lines.append(f":{emoji}: {r['service']}: {r['status']}")
        try:
            await slack_client.post_message(channel=slack_channel, text="\n".join(lines))
        except Exception as e:
            logger.error(f"Failed to post health report to Slack: {e}")

    return results


async def hourly_n8n_workflow_check():
    """
    Hourly check of active n8n workflows.

    Lists all workflows via the n8n API and logs their status.
    """
    if not settings.n8n_api_key:
        logger.warning("Skipping n8n workflow check: N8N_API_KEY not set")
        return []

    url = f"{settings.n8n_url}/api/v1/workflows"
    headers = {
        "X-N8N-API-KEY": settings.n8n_api_key,
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            workflows = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(workflows, list):
                workflows = []

        active = [w for w in workflows if w.get("active", False)]
        inactive = [w for w in workflows if not w.get("active", False)]

        logger.info(f"=== n8n Workflow Check: {len(active)} active, {len(inactive)} inactive ===")
        for wf in active:
            logger.info(f"  [ACTIVE]   {wf.get('name', 'unnamed')} (id={wf.get('id')})")
        for wf in inactive:
            logger.info(f"  [INACTIVE] {wf.get('name', 'unnamed')} (id={wf.get('id')})")

        return {
            "total": len(workflows),
            "active": len(active),
            "inactive": len(inactive),
            "workflows": [
                {"id": w.get("id"), "name": w.get("name"), "active": w.get("active", False)}
                for w in workflows
            ],
        }

    except Exception as e:
        logger.error(f"n8n workflow check failed: {e}")
        return {"error": str(e)}


def register_default_jobs(slack_client=None, slack_channel: str = ""):
    """Register the built-in scheduled jobs."""
    if not scheduler:
        logger.error("Cannot register jobs: scheduler not initialized")
        return

    # Daily health report at noon (12:00)
    add_cron_job(
        func=daily_health_report,
        job_id="daily_health_report",
        cron_expression="0 12 * * *",
        slack_client=slack_client,
        slack_channel=slack_channel,
    )

    # Hourly n8n workflow status check (every hour at :00)
    add_cron_job(
        func=hourly_n8n_workflow_check,
        job_id="hourly_n8n_check",
        cron_expression="0 * * * *",
    )

    # Cleanup expired user cron jobs (every hour at :30)
    add_cron_job(
        func=_cleanup_expired_jobs,
        job_id="_cleanup_expired_jobs",
        cron_expression="30 * * * *",
    )

    job_count = len(scheduler.get_jobs()) if scheduler else 0
    logger.info(f"Registered {job_count} default scheduled jobs")


# ---------------------------------------------------------------------------
# User-managed cron jobs
# ---------------------------------------------------------------------------

DEFAULT_JOB_IDS = {"daily_health_report", "hourly_n8n_check", "_cleanup_expired_jobs"}
_user_jobs: dict[str, dict] = {}


def _validate_cron_interval(cron_expression: str, min_minutes: int) -> bool:
    """
    Check that a cron expression does not fire more frequently than *min_minutes*.

    Returns True if the interval is acceptable, False otherwise.
    """
    parts = cron_expression.split()
    if len(parts) != 5:
        return False

    minute_field = parts[0]
    hour_field = parts[1]

    # "* * * * *" fires every minute
    if minute_field == "*" and hour_field == "*":
        return 1 >= min_minutes

    # "*/N * * * *" fires every N minutes
    if minute_field.startswith("*/") and hour_field == "*":
        try:
            n = int(minute_field[2:])
        except ValueError:
            return False
        return n >= min_minutes

    # Specific minute(s) + specific hour(s) → at most once per hour, always OK
    if hour_field != "*":
        return True

    # Specific minute(s) with wildcard hour, e.g. "0 * * * *" → once per hour
    return True


async def _trigger_n8n_workflow(
    job_id: str,
    workflow_id: str,
    trigger_method: str,
    webhook_path: str,
    payload: dict,
    n8n_url: str,
    n8n_api_key: str,
):
    """Fire an n8n workflow (called by APScheduler)."""
    logger.info(f"Cron job '{job_id}' triggering n8n workflow (method={trigger_method})")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if trigger_method == "webhook":
                url = f"{n8n_url}/webhook/{webhook_path}"
                resp = await client.post(url, json=payload or {})
            else:
                url = f"{n8n_url}/api/v1/workflows/{workflow_id}/execute"
                headers = {"X-N8N-API-KEY": n8n_api_key, "Content-Type": "application/json"}
                resp = await client.post(url, json=payload or {}, headers=headers)

            resp.raise_for_status()
            status = "success"
            logger.info(f"Cron job '{job_id}' triggered successfully (HTTP {resp.status_code})")
    except Exception as e:
        status = f"error: {e}"
        logger.error(f"Cron job '{job_id}' failed: {e}")

    if job_id in _user_jobs:
        _user_jobs[job_id]["last_run"] = datetime.now(timezone.utc).isoformat()
        _user_jobs[job_id]["last_status"] = status


def create_user_cron_job(
    job_id: str,
    cron_expression: str,
    workflow_id: str,
    trigger_method: str = "webhook",
    webhook_path: str = "",
    payload: dict | None = None,
    description: str = "",
    permanent: bool = False,
    n8n_url: str = "",
    n8n_api_key: str = "",
    min_interval_minutes: int = 1,
    max_user_jobs: int = 10,
    default_expiry_hours: int = 24,
) -> dict:
    """
    Create a user-managed cron job that triggers an n8n workflow.

    Returns a result dict with success status and metadata.
    """
    if not scheduler:
        return {"success": False, "error": "Scheduler not initialized"}

    # Validate cron format
    parts = cron_expression.split()
    if len(parts) != 5:
        return {"success": False, "error": f"Invalid cron expression (need 5 fields): {cron_expression}"}

    # Prevent overwriting default jobs
    if job_id in DEFAULT_JOB_IDS:
        return {"success": False, "error": f"Cannot overwrite default job '{job_id}'"}

    # Validate minimum interval
    if not _validate_cron_interval(cron_expression, min_interval_minutes):
        return {
            "success": False,
            "error": f"Cron interval too frequent. Minimum is every {min_interval_minutes} minute(s).",
        }

    # Enforce max user jobs (excluding this job if it already exists)
    existing_count = sum(1 for jid in _user_jobs if jid != job_id)
    if existing_count >= max_user_jobs:
        return {"success": False, "error": f"Maximum of {max_user_jobs} user jobs reached"}

    # Calculate expiry
    now = datetime.now(timezone.utc)
    expires_at = None if permanent else (now + timedelta(hours=default_expiry_hours)).isoformat()

    # Build CronTrigger
    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )

    # Register with APScheduler
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
            "n8n_url": n8n_url or settings.n8n_url,
            "n8n_api_key": n8n_api_key or settings.n8n_api_key,
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
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "last_run": None,
        "last_status": None,
    }

    logger.info(f"User cron job '{job_id}' created (cron={cron_expression}, permanent={permanent})")
    return {"success": True, "job": _user_jobs[job_id]}


def delete_user_cron_job(job_id: str) -> dict:
    """Delete a user-managed cron job."""
    if job_id in DEFAULT_JOB_IDS:
        return {"success": False, "error": f"Cannot delete default job '{job_id}'"}

    if job_id not in _user_jobs:
        return {"success": False, "error": f"User job '{job_id}' not found"}

    # Remove from APScheduler
    if scheduler:
        try:
            scheduler.remove_job(job_id)
        except Exception as e:
            logger.warning(f"Could not remove job '{job_id}' from scheduler: {e}")

    # Remove metadata
    del _user_jobs[job_id]
    logger.info(f"User cron job '{job_id}' deleted")
    return {"success": True, "message": f"Job '{job_id}' deleted"}


def update_user_cron_job(
    job_id: str,
    cron_expression: str | None = None,
    permanent: bool | None = None,
    min_interval_minutes: int = 1,
    default_expiry_hours: int = 24,
) -> dict:
    """Update the schedule or permanence of an existing user cron job."""
    if job_id not in _user_jobs:
        return {"success": False, "error": f"User job '{job_id}' not found"}

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

    # Reschedule if cron_expression changed
    if cron_expression is not None:
        parts = cron_expression.split()
        if len(parts) != 5:
            return {"success": False, "error": f"Invalid cron expression (need 5 fields): {cron_expression}"}

        if not _validate_cron_interval(cron_expression, min_interval_minutes):
            return {
                "success": False,
                "error": f"Cron interval too frequent. Minimum is every {min_interval_minutes} minute(s).",
            }

        meta["cron_expression"] = cron_expression

        if scheduler:
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
            try:
                scheduler.reschedule_job(job_id, trigger=trigger)
            except Exception as e:
                return {"success": False, "error": f"Failed to reschedule: {e}"}

    logger.info(f"User cron job '{job_id}' updated")
    return {"success": True, "job": meta}


def get_user_jobs() -> list[dict]:
    """Return all user-managed cron jobs with their metadata and next run time."""
    results = []
    for job_id, meta in _user_jobs.items():
        entry = dict(meta)
        # Attach next_run from APScheduler
        if scheduler:
            ap_job = scheduler.get_job(job_id)
            entry["next_run"] = str(ap_job.next_run_time) if ap_job else None
        else:
            entry["next_run"] = None
        results.append(entry)
    return results


async def _cleanup_expired_jobs():
    """Remove expired non-permanent user jobs (runs on schedule)."""
    now = datetime.now(timezone.utc)
    expired_ids = []

    for job_id, meta in _user_jobs.items():
        if meta.get("permanent"):
            continue
        expires_at = meta.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) <= now:
            expired_ids.append(job_id)

    for job_id in expired_ids:
        logger.info(f"Cleaning up expired user job '{job_id}'")
        delete_user_cron_job(job_id)

    if expired_ids:
        logger.info(f"Expired job cleanup: removed {len(expired_ids)} job(s)")
    return {"removed": expired_ids}
