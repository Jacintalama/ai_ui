"""The background worker that runs the steps of a started team job.

A job is started by its owner pressing Start on the plan card
(routes_agent_jobs). From then on nobody has to be watching: this loop,
started in main.py's lifespan next to the scheduler, claims the next step,
runs it as an ordinary agent turn and posts the result in the team chat. See
docs/plans/2026-10-14-agent-team-jobs-design.md.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

#: job id -> the asyncio task running that job's step right now. A job runs
#: one step at a time (agent_job_store.claim_next_step), so one task per job
#: is all Stop ever has to find.
_RUNNING: dict[str, asyncio.Task] = {}

#: Set by wake(). Made per event loop, not at import: an asyncio.Event binds
#: to the loop that first waits on it, and the tests run a loop per test.
_WAKE: asyncio.Event | None = None
_WAKE_LOOP: asyncio.AbstractEventLoop | None = None


def _wake_event() -> asyncio.Event:
    global _WAKE, _WAKE_LOOP
    loop = asyncio.get_running_loop()
    if _WAKE is None or _WAKE_LOOP is not loop:
        _WAKE = asyncio.Event()
        _WAKE_LOOP = loop
    return _WAKE


def wake() -> None:
    """Have the loop look for work now rather than at its next poll, so a
    job starts the moment Start is pressed. Never raises."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Not on the loop (a thread, a test helper). Hand the wake to the
        # loop the worker waits on, if there is one; otherwise the next poll
        # finds the work anyway, since a wake is only ever a shortcut.
        try:
            event, loop = _WAKE, _WAKE_LOOP
            if event is not None and loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(event.set)
        except Exception:                                   # noqa: BLE001
            logger.warning("job worker: wake failed", exc_info=True)
        return
    _wake_event().set()


async def _wait_for_work(timeout: float) -> None:
    """Sleep until woken or until `timeout` seconds pass, whichever is first."""
    event = _wake_event()
    try:
        await asyncio.wait_for(event.wait(), timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        event.clear()


def cancel(job_id: str) -> bool:
    """Cancel the task running this job's step, if one is. True if it was.

    The job's row is the store's to cancel (agent_job_store.cancel). This
    only stops the work: the turn in flight is abandoned, and because a
    stopped step is skipped and finish_step only closes a running one, a
    result that somehow lands later is never recorded or posted.
    """
    task = _RUNNING.get(job_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True
