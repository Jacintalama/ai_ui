"""`/run-now` fires a Claude Code agent, and nothing bounded how often.

The route resolves the caller, scopes the schedule to its owner, then fires
`asyncio.create_task(_finalize_run(sched))` and answers `{"status":
"dispatched"}` — every time, immediately. `_RUN_SEMAPHORE` caps CONCURRENCY at
3 so the box will not OOM, but a semaphore is a queue, not a bound: a burst of
clicks piles up behind it and the real cron-scheduled runs starve at the back.

The honest bound is the honest answer: refuse while a run for that schedule is
already in flight. It needs no new quota, no new column and no new number to
tune, and the user is told something true rather than being handed a
"dispatched" that means "twelfth in line".

The in-flight signal is `scheduler._IN_FLIGHT`, a set of schedule ids added by
`dispatch_run` and removed in `_finalize_run`'s `finally`. Deliberately NOT
`Schedule.last_run_status == "running"`, the DB field that looks like the
obvious candidate: a run is an in-process `asyncio.Task` that does not survive a
restart, while the row does. A crash mid-run would leave the row claiming
"running" forever with nothing to clear it, and `run-now` — the button you
press when something is stuck — would be the one thing that stayed refused. It
would also wedge permanently for a spent `run_once` schedule, which no tick will
ever fire again. The set has exactly the lifetime of the thing it describes.

Marking happens in `dispatch_run`, synchronously, not inside the coroutine:
`create_task` does not run a single line until the loop next yields, so a check
made inside `_finalize_run` would let a double-click through.

Operators and admins keep today's behaviour, like every other schedule limit.
"""
import asyncio
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()
os.environ.setdefault("CRON_SHARED_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

import routes_schedules  # noqa: E402
import scheduler  # noqa: E402
from main import app  # noqa: E402
from models import Schedule  # noqa: E402

OWNER = "u@x.com"
OTHER = "someone-else@x.com"
ADMIN_HEADERS = {"X-User-Email": "a@x.com", "X-User-Admin": "true"}
OPERATOR_HEADERS = {"X-Cron-Secret": os.environ["CRON_SHARED_SECRET"]}


def _sched(owner=OWNER, cron="0 9 * * *"):
    return Schedule(id=uuid.uuid4(), user_email=owner, name="nightly",
                    cron_expr=cron, tz="UTC", persona="", prompt="do a thing",
                    enabled=True)


class _FakeSession:
    """Answers _scoped_schedule / _tick_once / _finalize_run alike."""

    def __init__(self, rows):
        self._rows = list(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        rows = self._rows

        class _R:
            def scalars(self):
                class _S:
                    def all(self_):
                        return list(rows)
                return _S()

            def scalar_one_or_none(self):
                return rows[0] if rows else None
        return _R()

    def add(self, obj):
        pass

    async def commit(self):
        return None


@pytest.fixture
def bench(monkeypatch):
    """Install fake sessions and a run whose completion the test controls.

    The gate is what makes "in flight" observable: the agent run parks on it,
    so the second request arrives while the first is genuinely still going —
    the real condition, not a flag poked into place by the test.
    """
    state = {"gate": asyncio.Event(), "runs": 0, "raise": False}

    async def _gated_run(sched):
        state["runs"] += 1
        await state["gate"].wait()
        if state["raise"]:
            raise RuntimeError("the agent fell over")
        return "ok", "all done", None

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _gated_run)

    def _install(*rows):
        monkeypatch.setattr(routes_schedules, "session",
                            lambda: _FakeSession(rows))
        monkeypatch.setattr(scheduler, "session", lambda: _FakeSession(rows))

    state["install"] = _install
    try:
        yield state
    finally:
        # Never leave a parked run holding a slot for the next test.
        state["gate"].set()


async def _settle():
    """Let `create_task`'d coroutines actually start / finish.

    `create_task` schedules; it does not run. Without this the run counter
    reads zero and every "is it in flight" question is asked before anything
    has begun.
    """
    for _ in range(20):
        await asyncio.sleep(0)


async def _run_now(schedule_id, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(f"/schedules/{schedule_id}/run-now", headers=headers)
    await _settle()
    return resp


async def _let_the_run_finish(state):
    """Release the parked run and let its `finally` actually execute."""
    state["gate"].set()
    await _settle()


# ---------------------------------------------------------------------------
# The bound
# ---------------------------------------------------------------------------

async def test_the_first_run_now_is_still_dispatched(bench):
    s = _sched()
    bench["install"](s)
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dispatched"
    assert bench["runs"] == 1


async def test_a_second_run_now_is_refused_while_the_first_is_in_flight(bench):
    s = _sched()
    bench["install"](s)
    assert (await _run_now(s.id, {"X-User-Email": OWNER})).status_code == 200
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 409, (
        f"a second agent run was queued behind the first: {r.status_code} {r.text}")
    assert bench["runs"] == 1, "the refused request started an agent anyway"


async def test_the_refusal_explains_itself(bench):
    """A bare 409 tells the user their button is broken. The true reason —
    it is already running — is also the reassuring one."""
    s = _sched()
    bench["install"](s)
    await _run_now(s.id, {"X-User-Email": OWNER})
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    detail = r.json()["detail"].lower()
    assert "already running" in detail, f"unhelpful refusal: {detail!r}"


async def test_run_now_works_again_once_the_run_finishes(bench):
    """The bound is "one at a time", not "once"."""
    s = _sched()
    bench["install"](s)
    await _run_now(s.id, {"X-User-Email": OWNER})
    await _let_the_run_finish(bench)
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 200, (
        f"the schedule stayed blocked after its run finished: {r.text}")
    assert bench["runs"] == 2


async def test_a_run_that_blows_up_does_not_wedge_the_schedule(bench):
    """`finally`, not "on success". A failed agent run must not be the thing
    that makes run-now permanently unavailable — that is the button you press
    precisely when a run has gone wrong."""
    s = _sched()
    bench["install"](s)
    bench["raise"] = True
    await _run_now(s.id, {"X-User-Email": OWNER})
    await _let_the_run_finish(bench)
    bench["gate"] = asyncio.Event()
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 200, (
        f"a crashed run left the schedule permanently blocked: {r.text}")


async def test_the_bound_is_per_schedule(bench):
    """One user's stuck schedule must not stop their other one."""
    a, b = _sched(), _sched()
    bench["install"](a, b)
    assert (await _run_now(a.id, {"X-User-Email": OWNER})).status_code == 200
    # The fake session answers _scoped_schedule with the first row, so target
    # `a` again only through its own id; `b` is a different id entirely.
    bench["install"](b, a)
    r = await _run_now(b.id, {"X-User-Email": OWNER})
    assert r.status_code == 200, (
        f"running schedule A blocked unrelated schedule B: {r.text}")


async def test_a_cron_dispatched_run_also_blocks_run_now(bench):
    """The point is "a run is in flight", not "a run-now is in flight". The
    scheduler's own tick has to mark it too, or a user can double the load on
    the box by clicking at exactly the wrong minute."""
    s = _sched(cron="* * * * *")
    bench["install"](s)
    await scheduler._tick_once()
    await _settle()
    assert bench["runs"] == 1, "the tick did not fire the schedule"
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 409, (
        f"run-now stacked a second agent on top of a live cron run: {r.text}")


# ---------------------------------------------------------------------------
# Who is exempt
# ---------------------------------------------------------------------------

async def test_an_operator_is_unaffected(bench):
    """scripts/manage_schedules.py and the cron-runner keep working unchanged,
    as they do for every other schedule limit."""
    s = _sched()
    bench["install"](s)
    assert (await _run_now(s.id, OPERATOR_HEADERS)).status_code == 200
    r = await _run_now(s.id, OPERATOR_HEADERS)
    assert r.status_code == 200, f"the operator path lost run-now: {r.text}"


async def test_an_admin_is_unaffected(bench):
    """The bound protects the box from casual use; it is not a security
    boundary, and the admin header is gateway-set.

    An admin is still SCOPED to their own schedules here — `_resolve_caller`
    hands `_scoped_schedule` their email, and `_is_admin` only ever waives
    limits — so this is an admin acting on a schedule of their own.
    """
    s = _sched(owner="a@x.com")
    bench["install"](s)
    assert (await _run_now(s.id, ADMIN_HEADERS)).status_code == 200
    r = await _run_now(s.id, ADMIN_HEADERS)
    assert r.status_code == 200, f"an admin was bounded by run-now: {r.text}"


async def test_an_operators_run_still_blocks_the_owner(bench):
    """Exempt from the refusal, not exempt from the marking — otherwise a
    schedule the cron-runner is already running looks idle to its owner and
    they can stack a second agent on top of it."""
    s = _sched()
    bench["install"](s)
    assert (await _run_now(s.id, OPERATOR_HEADERS)).status_code == 200
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 409, (
        f"an operator's live run was invisible to the schedule's owner: {r.text}")


# ---------------------------------------------------------------------------
# Nothing else moved
# ---------------------------------------------------------------------------

async def test_a_missing_schedule_is_still_404(bench):
    bench["install"]()
    r = await _run_now(uuid.uuid4(), {"X-User-Email": OWNER})
    assert r.status_code == 404


async def test_someone_elses_schedule_is_still_404(bench):
    """Scoped before bounded — a stranger must not learn from a 409 that
    someone else's schedule exists and is busy."""
    s = _sched(owner=OTHER)
    bench["install"](s)
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 404, r.text
    assert bench["runs"] == 0


async def test_no_auth_at_all_is_still_403(bench):
    s = _sched()
    bench["install"](s)
    r = await _run_now(s.id, {})
    assert r.status_code == 403


async def test_a_row_left_claiming_running_does_not_block_anything(bench):
    """Pins the choice of signal against the tempting refactor, behaviourally.

    `last_run_status` looks like the obvious in-flight field — the tick sets it
    to "running" before dispatching. But it survives a process restart and the
    asyncio.Task it would describe does not, so a crash mid-run leaves the row
    claiming "running" with nothing left to clear it. Gating on it would make
    run-now — the button you press precisely when something is stuck — the one
    thing that stayed refused, and permanently so for a spent one-off that no
    tick will ever fire again.

    This is that exact state: a stale row, an empty process. It must run.
    """
    s = _sched()
    s.last_run_status = "running"
    bench["install"](s)
    r = await _run_now(s.id, {"X-User-Email": OWNER})
    assert r.status_code == 200, (
        "a schedule whose row was left claiming 'running' by a crashed process "
        f"can never be run again: {r.status_code} {r.text}")
