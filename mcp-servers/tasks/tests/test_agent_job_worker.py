"""The background worker that runs a started team job's steps.

Everything outside the worker is a fake: the store, the turn runner, the
chat posting and the live feed. No model is called and no database is
touched.
"""
import asyncio

import pytest

import agent_job_worker as worker


@pytest.fixture(autouse=True)
def _fresh_worker(monkeypatch):
    worker._RUNNING.clear()
    # A loop from an earlier test leaves its slots behind; each test's loop
    # is its own event loop.
    monkeypatch.setattr(worker, "_SLOTS", None)
    yield
    worker._RUNNING.clear()


async def test_wake_ends_an_idle_wait_at_once():
    waiter = asyncio.ensure_future(worker._wait_for_work(30))
    await asyncio.sleep(0)
    assert not waiter.done()
    worker.wake()
    await asyncio.wait_for(waiter, 1)


async def test_wake_outside_a_running_loop_is_harmless():
    # Start is a request handler, always inside the loop, but a wake from
    # anywhere else must not raise into whoever called it.
    await asyncio.get_running_loop().run_in_executor(None, worker.wake)


async def test_cancel_cancels_only_that_jobs_running_step():
    async def forever():
        await asyncio.sleep(3600)

    mine = asyncio.ensure_future(forever())
    other = asyncio.ensure_future(forever())
    worker._RUNNING["job-1"] = mine
    worker._RUNNING["job-2"] = other
    assert worker.cancel("job-1") is True
    await asyncio.sleep(0)
    assert mine.cancelled()
    assert not other.done()
    other.cancel()


def test_cancel_with_nothing_running_is_a_no_op():
    assert worker.cancel("job-nobody") is False


# --- the worker running steps -------------------------------------------

import copy  # noqa: E402

import agent_activity  # noqa: E402

ROSTER = [{"id": "lead", "name": "Lena"}, {"id": "mia", "name": "Mia"},
          {"id": "ada", "name": "Ada"}, {"id": "dev", "name": "Dev"}]
FINAL_ASK = "Write the person a short final answer"
CALLS = [{"id": "call-1", "function": {"name": "send_email",
                                       "arguments": '{"to": "b@x.com"}'}}]


class FakeStore:
    """agent_job_store's rules, in memory: one step per job at a time, the
    oldest running job first, finish_step and set_status one-way."""

    def __init__(self):
        self.jobs = {}
        self.order = []
        self.claim_errors = 0
        self.claims = 0
        #: Step ids whose current attempt ran a tool (step_acted).
        self.acted = set()
        self.acted_error = None
        #: What each sweep_stuck call was told to leave alone, and what the
        #: next one returns.
        self.sweeps = []
        self.sweep_result = []

    def add(self, job_id, email, agent_ids, status="running"):
        self.jobs[job_id] = {
            "id": job_id, "user_email": email, "chat_id": "chat-" + email,
            "lead_agent_id": "lead", "request": "weekly summary for " + email,
            "status": status, "result": None,
            "steps": [{"id": f"{job_id}-s{i}", "job_id": job_id,
                       "position": i, "agent_id": a, "task": f"task {i}",
                       "status": "waiting", "attempts": 0, "result": None,
                       "run_id": None}
                      for i, a in enumerate(agent_ids, start=1)]}
        self.order.append(job_id)
        return self.jobs[job_id]

    def _step(self, step_id):
        for job in self.jobs.values():
            for st in job["steps"]:
                if st["id"] == step_id:
                    return job, st
        raise KeyError(step_id)

    async def claim_next_step(self):
        self.claims += 1
        if self.claim_errors:
            self.claim_errors -= 1
            raise RuntimeError("database went away")
        for job_id in self.order:
            job = self.jobs[job_id]
            if job["status"] != "running":
                continue
            if any(st["status"] == "running" for st in job["steps"]):
                continue
            waiting = [st for st in job["steps"] if st["status"] == "waiting"]
            if not waiting:
                continue
            st = waiting[0]
            st["status"] = "running"
            st["attempts"] += 1
            out = copy.deepcopy(st)
            out["job"] = copy.deepcopy(job)
            return out
        return None

    async def get(self, job_id):
        job = self.jobs.get(job_id)
        return copy.deepcopy(job) if job else None

    async def finish_step(self, step_id, status, result=None, run_id=None):
        _, st = self._step(step_id)
        if st["status"] != "running":
            return False
        st["status"], st["result"] = status, result
        return True

    async def sweep_stuck(self, exclude_job_ids=()):
        self.sweeps.append(list(exclude_job_ids))
        out, self.sweep_result = self.sweep_result, []
        return out

    async def finish_held_step(self, step_id, job_id, answer, reopen):
        job, st = self._step(step_id)
        if job["status"] != "needs_you" or st["status"] != "running":
            return False
        st["status"], st["result"] = "done", answer
        if reopen:
            job["status"] = "running"
        return True

    async def step_acted(self, step_id):
        if self.acted_error is not None:
            raise self.acted_error
        return step_id in self.acted

    async def requeue_step(self, step_id):
        _, st = self._step(step_id)
        if st["status"] == "running":
            st["status"] = "waiting"

    async def set_status(self, job_id, status, result=None):
        job = self.jobs[job_id]
        if job["status"] not in ("running", "needs_you"):
            return False
        job["status"] = status
        if result is not None:
            job["result"] = result
        if status in ("failed", "cancelled"):
            for st in job["steps"]:
                if st["status"] == "waiting":
                    st["status"] = "skipped"
        return True

    async def cancel(self, job_id, user_email):
        job = self.jobs[job_id]
        job["status"] = "cancelled"
        for st in job["steps"]:
            if st["status"] in ("waiting", "running"):
                st["status"] = "skipped"
        return True


class Harness:
    def __init__(self, monkeypatch):
        self.store = FakeStore()
        self.posted = []
        self.events = []
        self.turns = []
        self.answers = {}           # agent id -> outcomes, in order
        self.turn_delay = 0.0
        self.live = 0
        self.max_live = 0
        h = self

        async def run_turn(user_email, agent_id, messages, brief=False, **kw):
            h.turns.append({"email": user_email, "agent": agent_id,
                            "brief": brief,
                            "job_step": agent_activity.in_job_step(),
                            "text": messages[-1]["content"]})
            h.live += 1
            h.max_live = max(h.max_live, h.live)
            try:
                if h.turn_delay:
                    await asyncio.sleep(h.turn_delay)
                queue = h.answers.get(agent_id)
                outcome = queue.pop(0) if queue else None
                if isinstance(outcome, BaseException):
                    raise outcome
                if isinstance(outcome, dict):
                    return outcome
                if outcome is not None:
                    return {"answer": outcome, "notes": []}
                if FINAL_ASK in messages[-1]["content"]:
                    return {"answer": "All done for " + user_email,
                            "notes": []}
                return {"answer": f"{agent_id} result", "notes": []}
            finally:
                h.live -= 1

        async def agents_for(email):
            return list(ROSTER)

        async def post(email, message, pending=None, title=""):
            h.posted.append({"email": email, "message": dict(message),
                             "pending": pending})
            return True

        def publish(event, **kw):
            h.events.append((event, kw))

        monkeypatch.setattr(worker, "job_store", self.store)
        monkeypatch.setattr(worker, "_run_turn", run_turn)
        monkeypatch.setattr(worker, "_agents_for", agents_for)
        monkeypatch.setattr(worker, "post_to_room", post)
        monkeypatch.setattr(worker.agent_events, "publish", publish)
        monkeypatch.setattr(worker, "IDLE_POLL_SECONDS", 0.01)
        monkeypatch.setattr(worker, "ERROR_SLEEP_SECONDS", 0.01)

    def contents(self, email=None):
        return [p["message"].get("content") for p in self.posted
                if email is None or p["email"] == email]

    def named(self, event):
        return [kw for e, kw in self.events if e == event]


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


async def _run_until(cond, timeout=3.0):
    """Run the real loop until `cond()` holds, then stop it."""
    loop_task = asyncio.ensure_future(worker.job_loop())
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while not cond():
            assert not loop_task.done(), "the loop died"
            assert asyncio.get_running_loop().time() < deadline, "timed out"
            await asyncio.sleep(0.01)
        # Let anything already finishing settle.
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
        for task in list(worker._RUNNING.values()):
            task.cancel()


def _done(store, job_id):
    return lambda: store.jobs[job_id]["status"] in ("done", "failed",
                                                     "cancelled")


async def test_three_steps_run_in_order_and_the_lead_closes_the_job(h):
    h.store.add("job-1", "p@x.com", ["mia", "ada", "dev"])
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "done"
    assert job["result"] == "All done for p@x.com"
    assert [st["status"] for st in job["steps"]] == ["done"] * 3
    assert [t["agent"] for t in h.turns] == ["mia", "ada", "dev", "lead"]
    # Each turn is a job step with a brief, and sees the step it is.
    assert all(t["job_step"] and t["brief"] for t in h.turns)
    assert "2. Ada: task 2 <- this is your step" in h.turns[1]["text"]
    assert "Step 1, Mia: mia result" in h.turns[1]["text"]
    assert FINAL_ASK in h.turns[3]["text"]
    assert "Step 3, Dev: dev result" in h.turns[3]["text"]
    # Every result is posted with its step, then the lead's answer.
    posted = [p["message"] for p in h.posted]
    assert [(m.get("agent_id"), m.get("step"), m.get("of"))
            for m in posted] == [("mia", 1, 3), ("ada", 2, 3), ("dev", 3, 3),
                                 ("lead", None, None)]
    assert all(m["role"] == "assistant" and m["job_id"] == "job-1"
               for m in posted)
    assert posted[1]["agent_name"] == "Ada"
    assert posted[3]["content"] == "All done for p@x.com"
    # The feed: ids and numbers.
    assert [(kw["agent_id"], kw["step"], kw["of"])
            for kw in h.named("step_started")] == [("mia", 1, 3),
                                                   ("ada", 2, 3),
                                                   ("dev", 3, 3)]
    assert [kw["status"] for kw in h.named("step_finished")] == ["ok"] * 3
    assert h.named("job_finished") == [{"agent_id": "lead",
                                        "user_email": "p@x.com",
                                        "job_id": "job-1", "status": "done"}]
    assert {kw["agent_id"] for kw in h.named("speaking_started")} == {
        "mia", "ada", "dev", "lead"}


async def test_a_step_that_fails_once_is_retried(h):
    h.store.add("job-1", "p@x.com", ["mia", "ada", "dev"])
    h.answers["ada"] = [RuntimeError("boom"), "ada second try"]
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "done"
    assert job["steps"][1]["attempts"] == 2
    assert job["steps"][1]["result"] == "ada second try"
    assert [t["agent"] for t in h.turns] == ["mia", "ada", "ada", "dev",
                                             "lead"]
    assert "ada second try" in h.contents()


async def test_a_step_that_fails_twice_stops_the_job(h):
    h.store.add("job-1", "p@x.com", ["mia", "ada", "dev"])
    h.answers["ada"] = [RuntimeError("boom"), RuntimeError("boom again")]
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "failed"
    assert [st["status"] for st in job["steps"]] == ["done", "failed",
                                                     "skipped"]
    assert "dev" not in [t["agent"] for t in h.turns]
    note = h.posted[-1]["message"]
    assert note["agent_id"] == "lead" and note["agent_name"] == "Lena"
    assert note["content"].startswith("Ada could not finish step 2: ")
    assert note["content"].endswith(". The job stopped.")
    assert [kw["status"] for kw in h.named("step_finished")] == ["ok",
                                                                 "failed"]
    assert h.named("job_finished")[-1]["status"] == "failed"


async def test_a_failure_sentence_is_a_failure_not_a_result(h):
    from agent_runner import ROUTER_EXHAUSTED
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    h.answers["mia"] = [ROUTER_EXHAUSTED, ROUTER_EXHAUSTED]
    await _run_until(_done(h.store, "job-1"))
    assert h.store.jobs["job-1"]["status"] == "failed"
    assert ROUTER_EXHAUSTED not in h.contents()
    assert "free models are all busy" in h.posted[-1]["message"]["content"]


async def test_a_step_that_runs_out_of_time_is_a_failure(h, monkeypatch):
    monkeypatch.setattr(worker, "STEP_HARD_CAP_SECONDS", 0.02)
    h.turn_delay = 1.0
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "failed"
    assert job["steps"][0]["attempts"] == 2
    assert "ran out of time" in h.posted[-1]["message"]["content"]


async def test_a_step_that_asks_first_waits_for_the_person(h):
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    held = {"agent_id": "mia", "user_email": "p@x.com", "calls": CALLS,
            "conversation": [{"role": "user", "content": "x"}]}
    h.answers["mia"] = [{"answer": "May I send it?", "notes": [],
                         "pending": held}]
    await _run_until(lambda: h.store.jobs["job-1"]["status"] == "needs_you")
    # Give the loop a few more polls: nothing else may run for this job.
    claims = h.store.claims
    await _run_until(lambda: h.store.claims > claims + 5)
    job = h.store.jobs["job-1"]
    assert job["status"] == "needs_you"
    assert [st["status"] for st in job["steps"]] == ["running", "waiting"]
    assert [t["agent"] for t in h.turns] == ["mia"]
    post = h.posted[-1]
    assert post["message"]["content"] == "May I send it?"
    assert post["message"]["job_id"] == "job-1"
    assert post["message"]["awaiting"]["calls"][0]["function"]["name"] == \
        "send_email"
    ask_id = post["message"]["awaiting"]["ask_id"]
    stored = post["pending"][ask_id]
    assert stored["job_step_id"] == "job-1-s1"
    assert (stored["job_id"], stored["job_step"], stored["job_of"]) == (
        "job-1", 1, 2)
    assert stored["conversation"] == held["conversation"]
    assert not h.named("step_finished")


async def test_stop_cancels_the_running_step_and_nothing_is_posted(h):
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    h.turn_delay = 5.0
    loop_task = asyncio.ensure_future(worker.job_loop())
    try:
        for _ in range(300):
            if h.turns:
                break
            await asyncio.sleep(0.01)
        assert h.turns and "job-1" in worker._RUNNING
        step_task = worker._RUNNING["job-1"]
        await h.store.cancel("job-1", "p@x.com")
        assert worker.cancel("job-1") is True
        for _ in range(20):
            await asyncio.sleep(0.01)
        assert step_task.done()
        assert "job-1" not in worker._RUNNING
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
    assert h.posted == []
    assert not h.named("step_finished")
    assert [st["status"] for st in h.store.jobs["job-1"]["steps"]] == [
        "skipped", "skipped"]


async def test_a_late_result_after_stop_is_not_posted(h, monkeypatch):
    """Stop pressed while the turn was already returning: the row says
    skipped, so finish_step refuses and nothing reaches the chat."""
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    real = h.store.finish_step

    async def stopped_first(step_id, status, result=None, run_id=None):
        await h.store.cancel("job-1", "p@x.com")
        return await real(step_id, status, result, run_id)

    monkeypatch.setattr(h.store, "finish_step", stopped_first)
    await _run_until(_done(h.store, "job-1"))
    assert h.posted == []
    assert [t["agent"] for t in h.turns] == ["mia"]


async def test_no_more_than_two_steps_run_at_once(h):
    h.turn_delay = 0.05
    for i in range(3):
        h.store.add(f"job-{i}", f"p{i}@x.com", ["mia", "ada"])
    await _run_until(lambda: all(_done(h.store, f"job-{i}")()
                                 for i in range(3)), timeout=5)
    assert h.max_live == 2
    assert all(h.store.jobs[f"job-{i}"]["status"] == "done" for i in range(3))
    # Two people's jobs ran side by side: the second person's first turn
    # came before the first person's last one.
    order = [t["email"] for t in h.turns]
    last_p0 = len(order) - 1 - order[::-1].index("p0@x.com")
    assert order.index("p1@x.com") < last_p0
    # Each person's results went to that person only.
    for i in range(3):
        mine = h.contents(f"p{i}@x.com")
        assert f"All done for p{i}@x.com" in mine
        assert not [c for c in mine if "All done for" in c
                    and not c.endswith(f"p{i}@x.com")]


async def test_the_loop_survives_a_claim_that_raises(h):
    h.store.claim_errors = 1
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    await _run_until(_done(h.store, "job-1"))
    assert h.store.jobs["job-1"]["status"] == "done"
    assert h.store.claims >= 2


async def test_a_closing_turn_that_fails_still_finishes_the_job(h):
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    h.answers["lead"] = [RuntimeError("no summary")]
    await _run_until(_done(h.store, "job-1"))
    assert h.store.jobs["job-1"]["status"] == "done"
    assert h.posted[-1]["message"]["content"] == (
        "All steps are done; the summary could not be written.")
    assert h.named("job_finished")[-1]["status"] == "done"


async def test_a_step_whose_tool_already_ran_is_not_retried(h):
    """A retry would run the tool again: the email goes out twice."""
    h.store.add("job-1", "p@x.com", ["mia", "ada", "dev"])
    h.store.acted.add("job-1-s2")
    h.answers["ada"] = [RuntimeError("boom"), "ada second try"]
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "failed"
    assert [st["status"] for st in job["steps"]] == ["done", "failed",
                                                     "skipped"]
    assert [t["agent"] for t in h.turns] == ["mia", "ada"]
    note = h.posted[-1]["message"]
    assert note["agent_id"] == "lead"
    assert note["content"].startswith("Ada could not finish step 2: ")
    assert ("It was not retried because it had already acted."
            in note["content"])
    assert note["content"].endswith("The job stopped.")


async def test_a_step_that_cannot_be_checked_is_not_retried(h):
    """Not knowing whether the tool ran is not knowing it did not."""
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    h.store.acted_error = RuntimeError("db down")
    h.answers["mia"] = [RuntimeError("boom"), "mia second try"]
    await _run_until(_done(h.store, "job-1"))
    assert h.store.jobs["job-1"]["status"] == "failed"
    assert [t["agent"] for t in h.turns] == ["mia"]


async def test_a_broken_step_whose_tool_ran_is_not_put_back(h, monkeypatch):
    """The bookkeeping around a step broke (its result did not land) after
    its turn had acted: failed, not requeued."""
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    h.store.acted.add("job-1-s1")
    real = h.store.finish_step
    broke = []

    async def finish_once_broken(step_id, status, result=None, run_id=None):
        if not broke:
            broke.append(step_id)
            raise RuntimeError("write did not land")
        return await real(step_id, status, result, run_id)

    monkeypatch.setattr(h.store, "finish_step", finish_once_broken)
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "failed"
    assert [st["status"] for st in job["steps"]] == ["failed", "skipped"]
    assert [t["agent"] for t in h.turns] == ["mia"]


async def test_a_question_that_cannot_be_shown_fails_the_job(h, monkeypatch):
    """Nobody can answer a question nobody was shown: the job would wait on
    the person, holding their one running slot, for good."""
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    held = {"agent_id": "mia", "user_email": "p@x.com", "calls": CALLS,
            "conversation": [{"role": "user", "content": "x"}]}
    h.answers["mia"] = [{"answer": "May I send it?", "notes": [],
                         "pending": held}]
    tried = []

    async def post(email, message, pending=None, title=""):
        tried.append({"message": dict(message), "pending": pending})
        return not pending          # the question fails; a plain note lands

    monkeypatch.setattr(worker, "post_to_room", post)
    await _run_until(_done(h.store, "job-1"))
    job = h.store.jobs["job-1"]
    assert job["status"] == "failed"
    assert [st["status"] for st in job["steps"]] == ["failed", "skipped"]
    note = tried[-1]["message"]
    assert note["agent_id"] == "lead" and not tried[-1]["pending"]
    assert note["content"] == ("Mia had a question on step 1, but it could "
                               "not be shown. The job stopped.")
    assert h.named("job_finished")[-1]["status"] == "failed"


async def test_the_idle_loop_sweeps_and_leaves_work_in_flight_alone(
        h, monkeypatch):
    import agent_job_store
    monkeypatch.setattr(worker, "SWEEP_EVERY_SECONDS", 0)

    async def forever():
        await asyncio.sleep(3600)

    closing = asyncio.ensure_future(forever())
    worker._RUNNING["job-closing"] = closing
    h.store.sweep_result = [{"job_id": "job-9", "user_email": "p@x.com",
                             "lead_agent_id": "lead", "request": "weekly",
                             "status": "done",
                             "why": agent_job_store.WHY_NO_SUMMARY,
                             "agent_id": None, "position": None}]
    try:
        await _run_until(lambda: len(h.store.sweeps) >= 2)
    finally:
        closing.cancel()
    assert all("job-closing" in ex for ex in h.store.sweeps)
    note = h.posted[0]
    assert note["email"] == "p@x.com"
    assert note["message"] == {"role": "note", "content": worker.NO_SUMMARY,
                               "job_id": "job-9"}
    assert h.named("job_finished") == [{"agent_id": "lead",
                                        "user_email": "p@x.com",
                                        "job_id": "job-9", "status": "done"}]


async def test_a_sweep_that_raises_does_not_stop_the_loop(h, monkeypatch):
    monkeypatch.setattr(worker, "SWEEP_EVERY_SECONDS", 0)

    async def broken(exclude_job_ids=()):
        raise RuntimeError("db down")

    h.store.sweep_stuck = broken
    h.store.add("job-1", "p@x.com", ["mia", "ada"])
    await _run_until(_done(h.store, "job-1"))
    assert h.store.jobs["job-1"]["status"] == "done"


def test_the_worker_and_the_store_agree_on_the_attempts():
    import agent_job_store
    assert worker.MAX_ATTEMPTS == agent_job_store.MAX_ATTEMPTS


# --- a held step carries on after Yes or No ---------------------------------

def _held_job(h, agent_ids=("mia", "ada"), held_at=1):
    """A job as _hold leaves it: waiting on the person, the asking step
    still running, the ones before it done."""
    job = h.store.add("job-1", "p@x.com", list(agent_ids), status="needs_you")
    for st in job["steps"]:
        if st["position"] < held_at:
            st["status"], st["result"], st["attempts"] = "done", "earlier", 1
        elif st["position"] == held_at:
            st["status"], st["attempts"] = "running", 1
    return job


@pytest.fixture
def woken(monkeypatch):
    count = []
    monkeypatch.setattr(worker, "wake", lambda: count.append(1))
    return count


async def _settle():
    task = worker._RUNNING.get("job-1")
    if task is not None:
        await asyncio.wait_for(task, 2)


async def test_yes_finishes_the_held_step_and_the_job_runs_on(h, woken):
    _held_job(h)
    await worker.resume_after_answer("job-1-s1", {"answer": "Sent it.",
                                                  "notes": []},
                                     job_id="job-1")
    job = h.store.jobs["job-1"]
    assert job["steps"][0]["status"] == "done"
    assert job["steps"][0]["result"] == "Sent it."
    assert job["status"] == "running"
    assert woken
    # The chat drew the answer already; the worker does not post it twice.
    assert h.posted == []
    assert [(kw["agent_id"], kw["step"], kw["status"])
            for kw in h.named("step_finished")] == [("mia", 1, "ok")]


async def test_no_finishes_the_step_with_the_agents_own_words(h, woken):
    _held_job(h)
    await worker.resume_after_answer(
        "job-1-s1", {"answer": "I did not run that.", "notes": []},
        job_id="job-1")
    job = h.store.jobs["job-1"]
    assert job["steps"][0]["result"] == "I did not run that."
    assert job["status"] == "running"


async def test_a_step_that_asks_again_keeps_the_job_waiting(h, woken):
    _held_job(h)
    await worker.resume_after_answer(
        "job-1-s1", {"answer": "", "notes": [],
                     "pending": {"agent_id": "mia", "calls": CALLS}},
        job_id="job-1")
    job = h.store.jobs["job-1"]
    assert job["status"] == "needs_you"
    assert job["steps"][0]["status"] == "running"
    assert not woken and h.posted == []


async def test_an_answer_to_the_last_step_closes_the_job(h, woken):
    _held_job(h, held_at=2)
    await worker.resume_after_answer("job-1-s2", {"answer": "Sent it.",
                                                  "notes": []},
                                     job_id="job-1")
    await _settle()
    job = h.store.jobs["job-1"]
    assert job["status"] == "done"
    assert job["result"] == "All done for p@x.com"
    assert h.posted[-1]["message"]["agent_id"] == "lead"
    # The lead read both results, the held step's answer included.
    final = h.turns[-1]["text"]
    assert "Step 1, Mia: earlier" in final
    assert "Step 2, Ada: Sent it." in final
    assert h.named("job_finished")[-1]["status"] == "done"


async def test_an_answer_after_stop_changes_nothing(h, woken):
    _held_job(h)
    await h.store.cancel("job-1", "p@x.com")
    await worker.resume_after_answer("job-1-s1", {"answer": "Sent it.",
                                                  "notes": []},
                                     job_id="job-1")
    job = h.store.jobs["job-1"]
    assert job["status"] == "cancelled"
    assert [st["status"] for st in job["steps"]] == ["skipped", "skipped"]
    assert h.posted == [] and not woken


async def test_a_resume_that_failed_stops_the_job(h, woken):
    """No retry: on Yes the tool may already have run, and running the step
    again would ask for it again."""
    _held_job(h)
    await worker.resume_after_answer("job-1-s1", None, job_id="job-1")
    job = h.store.jobs["job-1"]
    assert job["status"] == "failed"
    assert [st["status"] for st in job["steps"]] == ["failed", "skipped"]
    assert h.posted[-1]["message"]["content"].startswith(
        "Mia could not finish step 1: ")
    assert h.named("job_finished")[-1]["status"] == "failed"


async def test_a_busy_model_after_the_answer_stops_the_job(h, woken):
    from agent_runner import ROUTER_EXHAUSTED
    _held_job(h)
    await worker.resume_after_answer(
        "job-1-s1", {"answer": ROUTER_EXHAUSTED, "notes": []},
        job_id="job-1")
    assert h.store.jobs["job-1"]["status"] == "failed"
    assert "free models are all busy" in h.posted[-1]["message"]["content"]


async def test_an_answer_reopens_the_job_in_one_write(h, woken, monkeypatch):
    """Finishing the step and reopening the job are one write: separately,
    a failure between them left the job waiting on the person with nothing
    held, which nothing would ever move."""
    _held_job(h)
    real = h.store.set_status

    async def no_reopen(job_id, status, result=None):
        if status == "running":
            raise RuntimeError("write did not land")
        return await real(job_id, status, result)

    monkeypatch.setattr(h.store, "set_status", no_reopen)
    await worker.resume_after_answer("job-1-s1", {"answer": "Sent it.",
                                                  "notes": []},
                                     job_id="job-1")
    job = h.store.jobs["job-1"]
    assert job["status"] == "running"
    assert job["steps"][0]["status"] == "done"
    assert woken


async def test_the_last_answer_is_closed_by_a_task_stop_can_find(h, woken,
                                                                 monkeypatch):
    """From the moment the last step finishes, the closing is in _RUNNING:
    the sweep leaves it alone, and Stop can cancel it."""
    _held_job(h, held_at=2)
    real = h.store.finish_held_step
    registered = []

    async def finish(step_id, job_id, answer, reopen):
        registered.append("job-1" in worker._RUNNING)
        return await real(step_id, job_id, answer, reopen)

    monkeypatch.setattr(h.store, "finish_held_step", finish)
    await worker.resume_after_answer("job-1-s2", {"answer": "Sent it.",
                                                  "notes": []},
                                     job_id="job-1")
    await _settle()
    assert registered == [True]
    assert h.store.jobs["job-1"]["status"] == "done"


async def test_a_resume_for_no_job_does_nothing(h, woken):
    await worker.resume_after_answer("step-x", {"answer": "x"}, job_id=None)
    await worker.resume_after_answer("step-x", {"answer": "x"},
                                     job_id="job-gone")
    assert h.posted == [] and not woken


# --- posting into the team chat ------------------------------------------

@pytest.fixture
def room(monkeypatch):
    import agent_chat_store
    import routes_agent_chat  # noqa: F401  (the helpers post_to_room uses)
    agent_chat_store._SESSIONS.clear()
    saved = []
    stored_row = {"row": None}

    async def newest_chat(email, agent_id=None):
        return stored_row["row"]

    async def save_chat(email, s):
        saved.append((email, s.chat_id, [dict(m) for m in s.messages],
                      dict(s.pending)))

    async def create_chat(email, title, s, agent_id=None):
        return "chat-new"

    monkeypatch.setattr(agent_chat_store, "newest_chat", newest_chat)
    monkeypatch.setattr(agent_chat_store, "save_chat", save_chat)
    monkeypatch.setattr(agent_chat_store, "create_chat", create_chat)
    yield agent_chat_store, saved, stored_row
    agent_chat_store._SESSIONS.clear()


async def test_a_post_lands_in_the_saved_room_conversation(room):
    store, saved, row = room
    row["row"] = {"id": "chat-1", "messages": [
        {"role": "user", "content": "prepare the summary"},
        {"role": "job", "job_id": "job-1"}], "pending": {}, "summary": ""}
    msg = {"role": "assistant", "agent_id": "mia", "agent_name": "Mia",
           "content": "found them", "job_id": "job-1", "step": 1, "of": 2}
    assert await worker.post_to_room("p@x.com", msg) is True
    s = store.get_session("p@x.com", None)
    assert s.chat_id == "chat-1"
    assert s.messages[-1] == msg
    assert saved[-1][1] == "chat-1" and saved[-1][2][-1] == msg
    assert s.streaming is False


async def test_a_post_never_touches_a_round_about_to_run(room):
    store, saved, row = room
    s = store.get_session("p@x.com", None)
    s.chat_id = "chat-1"
    s.messages = [{"role": "user", "content": "first"},
                  {"role": "assistant", "content": "answer"},
                  {"role": "user", "content": "a new question"}]
    s.streaming = True
    msg = {"role": "assistant", "agent_id": "mia", "content": "step result",
           "job_id": "job-1", "step": 1, "of": 2}
    await worker.post_to_room("p@x.com", msg)
    # The unanswered question stays last, or the stream about to answer it
    # would read the conversation as answered and run no round.
    assert s.messages[-1]["content"] == "a new question"
    assert s.messages[-2] == msg
    assert s.streaming is True


async def test_a_held_question_is_stored_where_yes_and_no_find_it(room):
    store, saved, row = room
    s = store.get_session("p@x.com", None)
    s.chat_id = "chat-1"
    s.messages = [{"role": "assistant", "content": "earlier"}]
    held = {"agent_id": "mia", "calls": CALLS, "job_step_id": "s1"}
    await worker.post_to_room("p@x.com", {"role": "assistant",
                                          "content": "May I?"},
                              pending={"ask-1": held})
    assert s.pending["ask-1"] is held
    assert saved[-1][3] == {"ask-1": held}


async def test_a_post_that_cannot_save_does_not_raise(room, monkeypatch):
    store, saved, row = room

    async def broken(email, s):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "save_chat", broken)
    s = store.get_session("p@x.com", None)
    s.chat_id = "chat-1"
    # The shielded save logs its own failure; the post stays in the working
    # copy, which the next save writes.
    await worker.post_to_room("p@x.com", {"role": "assistant",
                                          "content": "x"})
    assert s.messages[-1]["content"] == "x"


async def test_a_room_with_no_conversation_yet_gets_one(room):
    store, saved, row = room
    await worker.post_to_room("p@x.com", {"role": "assistant",
                                          "content": "x"}, title="weekly")
    assert store.get_session("p@x.com", None).chat_id == "chat-new"
    assert saved and saved[-1][1] == "chat-new"


# --- starting with the service --------------------------------------------

async def test_start_background_recovers_then_starts_the_loop(monkeypatch):
    calls = []

    async def recover():
        calls.append("recover")
        return 2

    async def fake_loop():
        calls.append("loop")
        await asyncio.sleep(3600)

    monkeypatch.setattr(worker.job_store, "recover_after_restart", recover)
    monkeypatch.setattr(worker, "job_loop", fake_loop)
    monkeypatch.setattr(worker, "_LOOP_TASK", None)
    monkeypatch.delenv("AGENT_JOBS_ENABLED", raising=False)
    assert await worker.start_background() is True
    await asyncio.sleep(0)
    assert calls == ["recover", "loop"]
    # A second start does not run a second loop.
    assert await worker.start_background() is False
    worker._LOOP_TASK.cancel()


async def test_a_failed_recovery_still_starts_the_loop(monkeypatch):
    started = []

    async def recover():
        raise RuntimeError("db down")

    async def fake_loop():
        started.append(True)
        await asyncio.sleep(3600)

    monkeypatch.setattr(worker.job_store, "recover_after_restart", recover)
    monkeypatch.setattr(worker, "job_loop", fake_loop)
    monkeypatch.setattr(worker, "_LOOP_TASK", None)
    monkeypatch.delenv("AGENT_JOBS_ENABLED", raising=False)
    assert await worker.start_background() is True
    await asyncio.sleep(0)
    assert started == [True]
    worker._LOOP_TASK.cancel()


async def test_jobs_ended_by_the_restart_are_announced(h, monkeypatch):
    import agent_job_store
    ended = [{"job_id": "job-1", "user_email": "p@x.com",
              "lead_agent_id": "lead", "request": "weekly", "status": "failed",
              "why": agent_job_store.WHY_ACTED, "agent_id": "ada",
              "position": 2},
             {"job_id": "job-2", "user_email": "q@x.com",
              "lead_agent_id": "lead", "request": "monthly",
              "status": "failed", "why": agent_job_store.WHY_INTERRUPTED,
              "agent_id": "mia", "position": 1}]

    async def recover():
        return {"requeued": 0, "ended": ended}

    async def fake_loop():
        await asyncio.sleep(3600)

    h.store.recover_after_restart = recover
    monkeypatch.setattr(worker, "job_loop", fake_loop)
    monkeypatch.setattr(worker, "_LOOP_TASK", None)
    monkeypatch.delenv("AGENT_JOBS_ENABLED", raising=False)
    assert await worker.start_background() is True
    worker._LOOP_TASK.cancel()
    by_job = {p["message"]["job_id"]: p for p in h.posted}
    acted = by_job["job-1"]
    assert acted["email"] == "p@x.com"
    assert acted["message"]["agent_id"] == "lead"
    assert acted["message"]["content"] == (
        "Ada's step 2 was cut off by a restart after it had already acted, "
        "so it was not run again. The job stopped.")
    assert by_job["job-2"]["message"]["content"] == (
        "Mia could not finish step 1: it was cut off by a restart on its "
        "last try. The job stopped.")
    assert [(kw["job_id"], kw["status"]) for kw in h.named("job_finished")]         == [("job-1", "failed"), ("job-2", "failed")]


async def test_jobs_switched_off_start_nothing(monkeypatch):
    async def recover():
        raise AssertionError("must not run")

    monkeypatch.setattr(worker.job_store, "recover_after_restart", recover)
    monkeypatch.setattr(worker, "_LOOP_TASK", None)
    monkeypatch.setenv("AGENT_JOBS_ENABLED", "false")
    assert await worker.start_background() is False
    assert worker._LOOP_TASK is None
