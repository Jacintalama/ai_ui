"""The office's live feed: what an agent is doing, the moment it does it.

An in-process fan-out. tasks runs ONE uvicorn process (Dockerfile:46, no
--workers) and every agent turn runs inside it, on the one event loop, so a
dict of asyncio queues reaches every open office. No Redis, nothing else to
keep alive.

A fan-out, not a log: a page that was not connected misses what happened,
which is why every stream opens with `hello` and the page re-reads
/agents/activity on it. Spec:
docs/superpowers/specs/2026-09-29-live-agent-office-design.md
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: Twelve moments, each one a thing that really happened. Nothing else is
#: sent. The first five come from a run (agent_activity); the next three from
#: a chat round (routes_agent_chat): a bubble going out, and a meeting of more
#: than one speaker opening and closing; the last four from a team job
#: (Start and the job worker): a job and each of its steps beginning and
#: ending.
EVENTS = frozenset({"run_started", "tool_started", "tool_finished",
                    "handoff", "run_finished",
                    "speaking_started", "meeting_started", "meeting_ended",
                    "job_started", "step_started", "step_finished",
                    "job_finished"})

#: A meeting names at most this many people, so no caller can grow an event.
MAX_PARTICIPANTS = 20

#: Per open page. One that falls this far behind is dropped, not buffered:
#: the box has 3.8GB, and the browser reconnects and re-reads anyway.
MAX_QUEUE = 100


class Subscriber:
    __slots__ = ("user_email", "queue", "dropped")

    def __init__(self, user_email: str):
        self.user_email = user_email
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self.dropped = False


_SUBS: dict[str, set[Subscriber]] = {}


def subscribe(user_email: str) -> Subscriber:
    sub = Subscriber(user_email)
    _SUBS.setdefault(user_email, set()).add(sub)
    return sub


def unsubscribe(sub: Subscriber) -> None:
    subs = _SUBS.get(sub.user_email)
    if subs is None:
        return
    subs.discard(sub)
    if not subs:
        _SUBS.pop(sub.user_email, None)


def publish(event: str, *, agent_id: str | None, user_email: str | None,
            tool: str | None = None, target_agent_id: str | None = None,
            status: str | None = None, source: str | None = None,
            participants: list | None = None,
            chars: int | None = None, job_id: str | None = None,
            step: int | None = None, of: int | None = None) -> None:
    """Send one event to every open office of `user_email`. Never raises.

    No prose, by construction: there is no parameter for a question, an
    answer or a tool's arguments, the same rule agent_step follows. A bubble
    is described by its length (`chars`), never its words; a meeting by its
    people's ids in turn order; a job by its id and step numbers (`step` of
    `of`), never its request, tasks or results. The owner routes the event
    and is never put in it.
    """
    try:
        if event not in EVENTS or not agent_id or not user_email:
            return
        payload = {"event": event, "agent_id": agent_id,
                   "at": datetime.now(timezone.utc).isoformat()}
        if tool:
            payload["tool"] = tool
        if target_agent_id:
            payload["target_agent_id"] = target_agent_id
        if status:
            payload["status"] = status
        if source:
            payload["source"] = str(source)
        if participants:
            payload["participants"] = [str(p) for p in participants
                                       if p][:MAX_PARTICIPANTS]
        if job_id:
            payload["job_id"] = str(job_id)
        # Numbers only, and a bad one is dropped rather than sent or raised:
        # the page draws "step 2 of 4" from these and nothing else.
        for key, value in (("chars", chars), ("step", step), ("of", of)):
            if value is None:
                continue
            try:
                payload[key] = max(0, int(value))
            except (TypeError, ValueError):
                pass
        for sub in list(_SUBS.get(user_email, ())):
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                sub.dropped = True
                unsubscribe(sub)
            except Exception:                               # noqa: BLE001
                logger.warning("live office: a page refused an event",
                               exc_info=True)
    except Exception:                                       # noqa: BLE001
        logger.warning("live office: publish failed", exc_info=True)


async def stream(user_email: str, poll_seconds: float = 5.0):
    """Server-sent events for one open page, until it goes or is dropped.

    Subscribes on first iteration rather than at request time, so a request
    whose body is never iterated cannot leave a subscriber behind. The
    finally runs on a client disconnect too: EventSourceResponse cancels
    this generator when the connection closes.
    """
    sub = subscribe(user_email)
    try:
        yield {"event": "hello", "data": "{}"}
        while not sub.dropped:
            try:
                payload = await asyncio.wait_for(sub.queue.get(),
                                                 timeout=poll_seconds)
            except asyncio.TimeoutError:
                continue
            if sub.dropped:
                break
            yield {"event": payload["event"], "data": json.dumps(payload)}
    finally:
        unsubscribe(sub)
