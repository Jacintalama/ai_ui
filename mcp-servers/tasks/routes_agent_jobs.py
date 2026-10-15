"""Start, Cancel and Stop on a team job's plan card, and the Done badge.

The plan card (agent_chat_render.job_card) is the lead's proposal, posted in
the team chat by the round (routes_agent_chat._run_round). Nothing runs until
its owner presses Start here; from then on the background worker
(agent_job_worker) runs the steps. Every button answers with the card drawn
as the job now is, which htmx swaps in place of the one pressed.

Every route that names a job reads it through agent_job_store.for_owner
first. Another person's job id is a 404, the same as no job at all, so a
guessed id learns nothing about anybody's plan.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

import agent_chat_render as render
import agent_events
import agent_job_store as job_store
import agent_job_worker
from auth import CurrentUser, current_user
from routes_agent_turn import _agents_for

log = logging.getLogger(__name__)

router = APIRouter()

REFUSED_START = "This plan can no longer be started."


async def _names(email: str) -> dict[str, str]:
    """Agent id -> name for the card. The card falls back to ids when the
    roster cannot be read, which is uglier and still correct."""
    try:
        return {str(a.get("id")): str(a.get("name") or a.get("id"))
                for a in await _agents_for(email) if a.get("id")}
    except Exception:                                       # noqa: BLE001
        log.warning("agent jobs: could not read the roster for a card",
                    exc_info=True)
        return {}


async def _owned(job_id: str, email: str) -> dict:
    try:
        job = await job_store.for_owner(job_id, email)
    except Exception:                                       # noqa: BLE001
        # Not a 404: the job may well exist. A non-2xx leaves the card on the
        # page as it was, which is the honest drawing of "could not check".
        log.warning("agent jobs: could not read job %s", job_id, exc_info=True)
        raise HTTPException(status_code=503, detail="try again")
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return job


def _summary(job: dict, names: dict[str, str]) -> dict:
    """The card's status, in the shape jobs_for_chat gives the thread."""
    steps = job.get("steps") or []
    running = [st for st in steps if st.get("status") == "running"]
    current = str(running[0]["agent_id"]) if running else None
    return {"status": job.get("status"),
            "done": sum(1 for st in steps if st.get("status") == "done"),
            "total": len(steps),
            "current_agent_id": current,
            "current_name": (names.get(current) or current) if current else None}


def _card(job: dict, names: dict[str, str], note_text: str = "") -> str:
    lead = str(job.get("lead_agent_id") or "")
    steps = [{"name": names.get(str(st.get("agent_id"))) or st.get("agent_id"),
              "task": st.get("task")}
             for st in sorted(job.get("steps") or [],
                              key=lambda st: int(st.get("position") or 0))]
    return render.job_card(str(job["id"]), names.get(lead) or lead or "Agent",
                           steps, _summary(job, names), note_text=note_text)


async def _reread(job: dict, email: str) -> dict:
    """The job after a change, or as it was if it cannot be read again."""
    try:
        return await job_store.for_owner(job["id"], email) or job
    except Exception:                                       # noqa: BLE001
        log.warning("agent jobs: could not re-read job %s", job["id"],
                    exc_info=True)
        return job


@router.post("/tasks/agents/jobs/{job_id}/start", include_in_schema=False)
async def job_start(job_id: str,
                    user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    job = await _owned(job_id, user.email)
    names = await _names(user.email)
    try:
        started = await job_store.start(job_id, user.email)
    except Exception:                                       # noqa: BLE001
        log.warning("agent jobs: could not start job %s", job_id,
                    exc_info=True)
        started = False
    if not started:
        # Expired, already started or ended, or another job of theirs is
        # running. Which one is on the card's own status line.
        return HTMLResponse(_card(await _reread(job, user.email), names,
                                  REFUSED_START))
    steps = sorted(job.get("steps") or [],
                   key=lambda st: int(st.get("position") or 0))
    # Ids and a count only, as every event on the feed: the office walks the
    # people in this order and draws "step n of m" from `of`.
    agent_events.publish("job_started",
                         agent_id=str(job.get("lead_agent_id") or ""),
                         user_email=user.email, job_id=job_id, of=len(steps),
                         participants=[str(st["agent_id"]) for st in steps])
    agent_job_worker.wake()
    return HTMLResponse(_card(await _reread(job, user.email), names))


@router.post("/tasks/agents/jobs/{job_id}/cancel", include_in_schema=False)
async def job_cancel(job_id: str,
                     user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    """Cancel on a proposed plan, Stop on a running one: the same thing."""
    job = await _owned(job_id, user.email)
    names = await _names(user.email)
    try:
        cancelled = await job_store.cancel(job_id, user.email)
    except Exception:                                       # noqa: BLE001
        log.warning("agent jobs: could not cancel job %s", job_id,
                    exc_info=True)
        raise HTTPException(status_code=503, detail="try again")
    if cancelled:
        # The row first, then the work: with the steps already skipped, a
        # turn that finishes in the gap cannot be recorded (finish_step only
        # closes a running step), so the order never loses a Stop.
        agent_job_worker.cancel(job_id)
        agent_events.publish("job_finished",
                             agent_id=str(job.get("lead_agent_id") or ""),
                             user_email=user.email, job_id=job_id,
                             status="cancelled")
    return HTMLResponse(_card(await _reread(job, user.email), names))


@router.get("/tasks/agents/jobs/badge", include_in_schema=False)
async def job_badge(user: CurrentUser = Depends(current_user)) -> JSONResponse:
    """How many of this person's jobs ended while they were away."""
    try:
        n = await job_store.unseen_count(user.email)
    except Exception:                                       # noqa: BLE001
        # A badge is a nicety. No number is better than an error on a page
        # that polls this.
        log.warning("agent jobs: could not count unseen jobs", exc_info=True)
        n = 0
    return JSONResponse({"unseen": int(n or 0)})


@router.post("/tasks/agents/jobs/seen", include_in_schema=False)
async def job_seen(user: CurrentUser = Depends(current_user)) -> JSONResponse:
    try:
        await job_store.mark_seen(user.email)
    except Exception:                                       # noqa: BLE001
        log.warning("agent jobs: could not mark jobs seen", exc_info=True)
        return JSONResponse({"ok": False})
    return JSONResponse({"ok": True})
