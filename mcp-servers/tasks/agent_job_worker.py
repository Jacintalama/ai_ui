"""The background worker that runs the steps of a started team job.

A job is started by its owner pressing Start on the plan card
(routes_agent_jobs). From then on nobody has to be watching: this loop,
started in main.py's lifespan next to the scheduler, claims the next step,
runs it as an ordinary agent turn and posts the result in the team chat. See
docs/plans/2026-10-14-agent-team-jobs-design.md.
"""
import asyncio
import logging
import os

import agent_activity
import agent_chat_store as store
import agent_events
import agent_job_brief
import agent_job_store as job_store
import agent_routing
from routes_agent_turn import _agents_for, _run_turn
from routes_agents import _pending_for_page

logger = logging.getLogger(__name__)

#: Steps running at once, across everybody. A step is a full agent turn with
#: tools, and the box has 3.8 GB: the scheduler holds itself to 3 for the
#: same reason, and a chat round runs its agents one at a time.
MAX_PARALLEL_STEPS = 2

#: The longest one step may take, on top of the turn's own limits. A turn
#: that hangs past this is a failed attempt, so a stuck model cannot hold a
#: slot (and the person's one running job) forever.
STEP_HARD_CAP_SECONDS = 300

#: A first try and one retry. Most failures are a busy free model or a
#: transient error, which a second try gets past; one that fails twice is
#: not going to work on a third, and the person should hear why.
MAX_ATTEMPTS = 2

#: How long the loop sleeps when there is nothing to claim. Start wakes it at
#: once (wake()), so this only matters for work nobody announced, such as a
#: step requeued after a restart.
IDLE_POLL_SECONDS = 5

#: The pause after the loop itself hit an error, so a database that is down
#: costs a log line every few seconds rather than a CPU spinning on it.
ERROR_SLEEP_SECONDS = 5

#: Said in the chat when every step is done but the lead could not write the
#: closing answer. The job is still done: the results are all in the chat.
NO_SUMMARY = "All steps are done; the summary could not be written."

_TIMED_OUT = "it ran out of time"
_BROKE = "something went wrong on our side"
_NO_RESULT = "it gave no result"

#: job id -> the asyncio task running that job's step right now. A job runs
#: one step at a time (agent_job_store.claim_next_step), so one task per job
#: is all Stop ever has to find.
_RUNNING: dict[str, asyncio.Task] = {}

#: The loop started by start_background(). Held here because the event loop
#: only keeps a weak reference to a task, and a loop nobody refers to can be
#: collected while it waits.
_LOOP_TASK: asyncio.Task | None = None

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


def jobs_enabled() -> bool:
    """The off switch, read when the service starts. Off, no loop runs and
    the chat round proposes nothing (routes_agent_chat.JOBS_ENABLED)."""
    return os.environ.get("AGENT_JOBS_ENABLED", "true").lower() != "false"


async def start_background() -> bool:
    """Tidy up after a restart, then start the loop. True if it started.

    Called from main.py's lifespan. The tidy-up failing is logged and the
    loop starts anyway: steps left running by the last process then wait
    for the next restart, but every other job still runs.
    """
    global _LOOP_TASK
    if not jobs_enabled():
        logger.info("agent jobs are switched off; the job worker is not "
                    "started")
        return False
    if _LOOP_TASK is not None and not _LOOP_TASK.done():
        return False
    try:
        await job_store.recover_after_restart()
    except Exception:                                       # noqa: BLE001
        logger.warning("job worker: could not tidy up after the restart; "
                       "starting anyway", exc_info=True)
    _LOOP_TASK = asyncio.ensure_future(job_loop())
    return True


async def job_loop() -> None:
    """Claim a step, run it, repeat, forever.

    A slot is taken BEFORE a claim, never after: a claim flips the step to
    running in the database, and a step claimed while no slot was free
    would sit there marked running with nothing running it.

    Never dies on an error. Each pass is caught and logged, and a failing
    pass sleeps before the next, so a broken database does not spin.
    """
    slots = asyncio.Semaphore(MAX_PARALLEL_STEPS)
    while True:
        try:
            await slots.acquire()
            try:
                step = await job_store.claim_next_step()
            except BaseException:
                slots.release()
                raise
            if step is None:
                slots.release()
                await _wait_for_work(IDLE_POLL_SECONDS)
                continue
            _launch(step, slots)
        except asyncio.CancelledError:
            raise
        except Exception:                                   # noqa: BLE001
            logger.exception("job worker: the loop hit an error; carrying on")
            await asyncio.sleep(ERROR_SLEEP_SECONDS)


def _launch(step: dict, slots: asyncio.Semaphore) -> None:
    job_id = str((step.get("job") or {}).get("id") or step.get("job_id"))
    _RUNNING[job_id] = asyncio.ensure_future(
        _run_and_release(job_id, step, slots))


async def _run_and_release(job_id: str, step: dict,
                           slots: asyncio.Semaphore) -> None:
    """One step in its own task, so Stop can cancel exactly this one."""
    try:
        await run_step(step)
    except asyncio.CancelledError:
        # Stop. The store already skipped the step; there is nothing to
        # write, and nothing may be posted.
        logger.info("job worker: step %s of job %s stopped", step.get("id"),
                    job_id)
    except Exception:                                       # noqa: BLE001
        # The turn's own failures are handled inside run_step. This is the
        # bookkeeping around it failing (a write that did not land), which
        # would otherwise leave the step marked running for good.
        logger.exception("job worker: step %s of job %s broke",
                         step.get("id"), job_id)
        await _recover_broken(step)
    finally:
        if _RUNNING.get(job_id) is asyncio.current_task():
            _RUNNING.pop(job_id, None)
        slots.release()
        # The job's next step, or somebody else's, can go now.
        wake()


async def _recover_broken(step: dict) -> None:
    """Put a step whose bookkeeping broke back, or end it after its last
    attempt, so it cannot retry forever. Best effort: the database that
    broke the step may break this too."""
    try:
        if int(step.get("attempts") or 0) < MAX_ATTEMPTS:
            await job_store.requeue_step(step["id"])
        else:
            await job_store.finish_step(step["id"], "failed", _BROKE)
            await job_store.set_status(str(step["job"]["id"]), "failed")
    except Exception:                                       # noqa: BLE001
        logger.warning("job worker: could not put step %s back",
                       step.get("id"), exc_info=True)


def _room():
    """routes_agent_chat, imported when first needed.

    The worker posts into the team chat through the chat's own helpers
    (_hydrate, the shielded save, _failure_reason, _ask_id), and the chat
    imports this module to resume a held step after Yes or No. Importing it
    at the top here would make the two modules import each other; importing
    it on first use means that by the time anything runs, both are loaded.
    """
    import routes_agent_chat
    return routes_agent_chat


async def _names(email: str) -> dict[str, str]:
    """Agent id -> name. Ids stand in for names when the roster cannot be
    read: a result labelled by id is better than no result."""
    try:
        return {str(a.get("id")): str(a.get("name") or a.get("id"))
                for a in await _agents_for(email) if a.get("id")}
    except Exception:                                       # noqa: BLE001
        logger.warning("job worker: could not read the roster",
                       exc_info=True)
        return {}


def _ordered(steps) -> list[dict]:
    return sorted(steps or [], key=lambda st: int(st.get("position") or 0))


def _held(out) -> bool:
    return (isinstance(out, dict) and isinstance(out.get("pending"), dict)
            and bool(_pending_for_page(out["pending"])))


async def _turn(email: str, agent_id: str, name: str,
                messages: list[dict]) -> tuple[dict | None, str | None]:
    """Run one turn as a job step: (out, None), or (None, why it failed).

    A held turn (it stopped to ask) comes back as its out, pending and all.
    A failure sentence (routes_agent_chat._failure_reason), an empty answer
    or a PASS is a failure, not a result: posting "the free models are all
    busy" as step 2's result would brief step 3 with it.
    """
    try:
        with agent_activity.job_step():
            out = await asyncio.wait_for(
                _run_turn(email, agent_id, messages, brief=True),
                STEP_HARD_CAP_SECONDS)
    except asyncio.TimeoutError:
        return None, _TIMED_OUT
    except Exception:                                       # noqa: BLE001
        logger.warning("job worker: %s's turn raised", agent_id,
                       exc_info=True)
        return None, _BROKE
    if not isinstance(out, dict):
        return None, _BROKE
    answer = (out.get("answer") or "").strip()
    if _held(out):
        return dict(out, answer=answer), None
    failed = _room()._failure_reason(name, answer)
    if failed is not None:
        reason = failed[0].strip().rstrip(".")
        return None, reason[:1].lower() + reason[1:]
    if not answer or agent_routing.is_pass(answer):
        return None, _NO_RESULT
    return dict(out, answer=answer), None


async def run_step(step: dict) -> None:
    """Run one claimed step to its end: done, held, retried or failed."""
    job = step.get("job") or {}
    job_id = str(job["id"])
    email = str(job["user_email"])
    steps = _ordered(job.get("steps"))
    total = len(steps)
    position = int(step["position"])
    agent_id = str(step["agent_id"])
    names = await _names(email)
    name = names.get(agent_id) or agent_id

    agent_events.publish("step_started", agent_id=agent_id, user_email=email,
                         job_id=job_id, step=position, of=total)
    messages = agent_job_brief.step_messages(job.get("request") or "", steps,
                                             position, names)
    out, reason = await _turn(email, agent_id, name, messages)
    if _held(out):
        await _hold(job, step, out, name, total)
        return
    if out is None:
        await _failed(job, step, name, total, reason or _BROKE, names)
        return
    await _step_done(job, step, out["answer"], names)


async def _step_done(job: dict, step: dict, answer: str,
                     names: dict[str, str]) -> bool:
    """Record a step's answer, post it, and close the job after the last
    step. False when the step had been stopped: one-way, so its answer is
    neither recorded nor posted."""
    job_id = str(job["id"])
    email = str(job["user_email"])
    steps = _ordered(job.get("steps"))
    total = len(steps)
    position = int(step["position"])
    agent_id = str(step["agent_id"])
    name = names.get(agent_id) or agent_id
    if not await job_store.finish_step(step["id"], "done", answer):
        return False
    await post_to_room(email, {"role": "assistant", "agent_id": agent_id,
                               "agent_name": name, "content": answer,
                               "job_id": job_id, "step": position,
                               "of": total},
                       title=job.get("request") or "")
    agent_events.publish("step_finished", agent_id=agent_id, user_email=email,
                         job_id=job_id, step=position, of=total, status="ok")
    agent_events.publish("speaking_started", agent_id=agent_id,
                         user_email=email, chars=len(answer))
    if steps and position >= max(int(st["position"]) for st in steps):
        done = [dict(st, status="done", result=answer)
                if st["id"] == step["id"] else st for st in steps]
        await _close(job, done, names)
    return True


async def _hold(job: dict, step: dict, out: dict, name: str,
                total: int) -> None:
    """The step's agent wants to change something and asked first.

    The question goes into the team chat the way a round's does
    (routes_agent_chat._question_events): the full payload held server side
    under a fresh ask id, the calls alone on the page. The payload also
    names this step and its job, which is how a Yes or No finds its way back
    here (resume_after_answer). The job waits on the person; the step stays
    running, held, until they answer.
    """
    job_id = str(job["id"])
    email = str(job["user_email"])
    if not await job_store.set_status(job_id, "needs_you"):
        return
    raw = dict(out["pending"])
    raw["job_step_id"] = str(step["id"])
    raw["job_id"] = job_id
    page = _pending_for_page(raw)
    ask_id = _room()._ask_id()
    awaiting = dict(page)
    awaiting["ask_id"] = ask_id
    answer = out.get("answer") or ""
    await post_to_room(email, {"role": "assistant",
                               "agent_id": str(step["agent_id"]),
                               "agent_name": name, "content": answer,
                               "awaiting": awaiting, "job_id": job_id,
                               "step": int(step["position"]), "of": total},
                       pending={ask_id: raw}, title=job.get("request") or "")
    agent_events.publish("speaking_started", agent_id=str(step["agent_id"]),
                         user_email=email, chars=len(answer))


async def _failed(job: dict, step: dict, name: str, total: int, reason: str,
                  names: dict[str, str]) -> None:
    """Retry once; a second failure stops the job and the lead says why."""
    if int(step.get("attempts") or 0) < MAX_ATTEMPTS:
        await job_store.requeue_step(step["id"])
        return
    job_id = str(job["id"])
    email = str(job["user_email"])
    position = int(step["position"])
    if not await job_store.finish_step(step["id"], "failed", reason):
        return
    if not await job_store.set_status(job_id, "failed"):
        return
    lead_id = str(job.get("lead_agent_id") or "")
    await post_to_room(email, {
        "role": "assistant", "agent_id": lead_id,
        "agent_name": names.get(lead_id) or lead_id,
        "content": "%s could not finish step %d: %s. The job stopped."
                   % (name, position, reason),
        "job_id": job_id}, title=job.get("request") or "")
    agent_events.publish("step_finished", agent_id=str(step["agent_id"]),
                         user_email=email, job_id=job_id, step=position,
                         of=total, status="failed")
    agent_events.publish("job_finished", agent_id=lead_id, user_email=email,
                         job_id=job_id, status="failed")


async def _close(job: dict, steps: list[dict], names: dict[str, str]) -> None:
    """Every step is done: the lead writes the closing answer.

    The job is done whether or not the lead manages it: the results are all
    in the chat already, and a job left at running because a summary failed
    would hold the person's one running slot.
    """
    job_id = str(job["id"])
    email = str(job["user_email"])
    lead_id = str(job.get("lead_agent_id") or "")
    lead_name = names.get(lead_id) or lead_id
    messages = agent_job_brief.final_messages(job.get("request") or "", steps,
                                              names)
    out, _reason = await _turn(email, lead_id, lead_name, messages)
    # A closing turn that stops to ask is not a summary. The results are all
    # posted; holding the whole job on the lead's afterthought is worse.
    summary = out.get("answer") if out is not None and not _held(out) else None
    if not await job_store.set_status(job_id, "done", result=summary):
        return
    if summary:
        await post_to_room(email, {"role": "assistant", "agent_id": lead_id,
                                   "agent_name": lead_name,
                                   "content": summary, "job_id": job_id},
                           title=job.get("request") or "")
        agent_events.publish("speaking_started", agent_id=lead_id,
                             user_email=email, chars=len(summary))
    else:
        await post_to_room(email, {"role": "note", "content": NO_SUMMARY,
                                   "job_id": job_id},
                           title=job.get("request") or "")
    agent_events.publish("job_finished", agent_id=lead_id, user_email=email,
                         job_id=job_id, status="done")


def _place(messages: list[dict], message: dict) -> None:
    """Add a job's message to the conversation, behind any unanswered
    question at the end.

    A user message at the tail is how the chat stream knows a round is still
    owed (routes_agent_chat.agent_chat_stream): the send appends it, then
    the browser connects. A step result landing in that gap must not become
    the tail, or the stream would read the question as answered and run no
    round for it. Anywhere else, a round mid flight with its claim marker
    last included, appending is safe: the round drops its marker afterwards
    wherever it is.
    """
    at = len(messages)
    while at > 0 and (messages[at - 1] or {}).get("role") == "user":
        at -= 1
    messages.insert(at, message)


async def post_to_room(email: str, message: dict, pending: dict | None = None,
                       title: str = "") -> bool:
    """Put one job message into this person's team chat and save it.

    The same session, hydrate and shielded save the chat round uses, so the
    working copy a round may be writing into and the saved row stay one
    conversation. Never touches `streaming`: that flag belongs to whichever
    round holds the room, and a job is not a round. The open page learns of
    the post from the feed's job events and re-reads the thread.

    `pending` is {ask id: held payload} for a step that stopped to ask.
    Never raises: False when the post could not even be placed.
    """
    try:
        room = _room()
        s = store.get_session(email, None)
        await room._hydrate(email, s, None)
        _place(s.messages, message)
        if pending:
            s.pending.update(pending)
        if s.chat_id is None:
            # Nobody has written the room yet (the row failed when the
            # request was sent). Make it, as the first send would have.
            try:
                s.chat_id = await store.create_chat(
                    email, store.title_from(title or "Team job"), s)
            except Exception:                               # noqa: BLE001
                logger.warning("job worker: could not create the room "
                               "conversation; the post stays unsaved",
                               exc_info=True)
        await room._save_despite_cancel(email, s)
        return True
    except Exception:                                       # noqa: BLE001
        logger.exception("job worker: could not post into the team chat")
        return False
