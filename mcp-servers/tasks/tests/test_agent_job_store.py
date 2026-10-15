"""The agent job store against real Postgres.

DB tier: run inside a tasks container (the local dev stack's is fine) with
AIUI_TEST_DB=1 and a DATABASE_URL containing "test". Locally every test here
errors at setup, which is expected.

These use db_session_nondestructive: every person here is a made-up
jobtest-<tag>@example.com, and the tests delete exactly the jobs those people
own (the steps go with them, ON DELETE CASCADE). Nothing else is touched.

claim_next_step and recover_after_restart look across every person, because
that is what the worker needs. So a stray running job left by a crashed run
of this file would change what they return; the fixture below clears this
file's own leftovers first, matched on the jobtest- prefix.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text as sql_text

import agent_job_store as js
from db import session

pytestmark = pytest.mark.asyncio

PREFIX = "jobtest-"


def _who() -> str:
    return "%s%s@example.com" % (PREFIX, uuid.uuid4().hex[:8])


async def _purge_test_people() -> None:
    async with session() as s:
        for table in ("agent_job", "agent_step", "agent_run"):
            await s.execute(sql_text(
                "DELETE FROM tasks.%s WHERE user_email LIKE :p" % table),
                {"p": PREFIX + "%@example.com"})
        await s.commit()


@pytest.fixture
async def clean(db_session_nondestructive):
    await _purge_test_people()
    yield
    await _purge_test_people()


STEPS = [{"agent_id": "agent-mia", "task": "Find the three latest reports."},
         {"agent_id": "agent-ada", "task": "Compare them."},
         {"agent_id": "agent-dev", "task": "Draft a one page summary."}]


async def _proposed(email: str, chat_id: str | None = "chat-1") -> str:
    return await js.create_proposed(email, chat_id, "agent-lead",
                                    "prepare the weekly summary", STEPS)


async def _running(email: str) -> str:
    job_id = await _proposed(email)
    assert await js.start(job_id, email) is True
    return job_id


async def test_create_then_get_round_trip(clean):
    email = _who()
    job_id = await _proposed(email)
    job = await js.get(job_id)
    assert job["id"] == job_id
    assert job["user_email"] == email
    assert job["chat_id"] == "chat-1"
    assert job["lead_agent_id"] == "agent-lead"
    assert job["request"] == "prepare the weekly summary"
    assert job["status"] == "proposed"
    assert job["started_at"] is None and job["finished_at"] is None
    assert [(s["position"], s["agent_id"], s["task"], s["status"])
            for s in job["steps"]] == [
        (1, "agent-mia", "Find the three latest reports.", "waiting"),
        (2, "agent-ada", "Compare them.", "waiting"),
        (3, "agent-dev", "Draft a one page summary.", "waiting")]
    assert await js.get("no-such-job") is None


async def test_for_owner_hides_another_persons_job(clean):
    email = _who()
    job_id = await _proposed(email)
    assert (await js.for_owner(job_id, email))["id"] == job_id
    assert await js.for_owner(job_id, _who()) is None


async def test_start_only_from_proposed_and_only_by_the_owner(clean):
    email = _who()
    job_id = await _proposed(email)
    assert await js.start(job_id, _who()) is False, "not the owner"
    assert (await js.get(job_id))["status"] == "proposed"
    assert await js.start(job_id, email) is True
    job = await js.get(job_id)
    assert job["status"] == "running" and job["started_at"] is not None
    assert await js.start(job_id, email) is False, "already running"


async def test_one_running_job_per_person(clean):
    email = _who()
    await _running(email)
    second = await _proposed(email)
    assert await js.start(second, email) is False
    assert (await js.get(second))["status"] == "proposed"
    # Somebody else is not held up by it.
    other = _who()
    assert await js.start(await _proposed(other), other) is True


async def test_a_plan_older_than_a_day_cannot_be_started(clean):
    email = _who()
    job_id = await _proposed(email)
    async with session() as s:
        await s.execute(sql_text(
            "UPDATE tasks.agent_job SET created_at = now() - interval '25 hours' "
            "WHERE id = :id"), {"id": job_id})
        await s.commit()
    assert await js.start(job_id, email) is False


async def test_claim_hands_out_steps_in_order(clean):
    email = _who()
    job_id = await _running(email)
    for position in (1, 2, 3):
        step = await js.claim_next_step()
        assert step["job_id"] == job_id
        assert step["position"] == position
        assert step["status"] == "running" and step["attempts"] == 1
        assert step["job"]["id"] == job_id
        assert step["job"]["user_email"] == email
        assert await js.finish_step(step["id"], "done", "result %d" % position,
                                    run_id="run-%d" % position) is True
    assert await js.claim_next_step() is None
    steps = (await js.get(job_id))["steps"]
    assert [(s["status"], s["result"], s["run_id"]) for s in steps] == [
        ("done", "result 1", "run-1"), ("done", "result 2", "run-2"),
        ("done", "result 3", "run-3")]


async def test_a_job_never_has_two_steps_running(clean):
    # Steps of one job run one at a time: step 2 needs step 1's result.
    email = _who()
    await _running(email)
    first = await js.claim_next_step()
    assert first["position"] == 1
    assert await js.claim_next_step() is None


async def test_two_concurrent_claims_never_take_the_same_step(clean):
    a, b = _who(), _who()
    job_a, job_b = await _running(a), await _running(b)
    got = await asyncio.gather(js.claim_next_step(), js.claim_next_step())
    assert all(got), got
    assert {g["job_id"] for g in got} == {job_a, job_b}
    assert len({g["id"] for g in got}) == 2


async def test_two_concurrent_claims_on_one_job_take_one_step(clean):
    await _running(_who())
    got = await asyncio.gather(js.claim_next_step(), js.claim_next_step())
    taken = [g for g in got if g]
    assert len(taken) == 1 and taken[0]["position"] == 1


async def test_a_paused_job_hands_out_nothing(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    assert await js.set_status(job_id, "needs_you") is True
    assert await js.claim_next_step() is None
    # Its held step stays running: the answer finishes it (Task 11).
    assert (await js.get(job_id))["steps"][0]["status"] == "running"
    assert step["position"] == 1


async def test_requeue_puts_a_step_back_and_keeps_its_attempt(clean):
    email = _who()
    await _running(email)
    step = await js.claim_next_step()
    await js.requeue_step(step["id"])
    again = await js.claim_next_step()
    assert again["id"] == step["id"]
    assert again["attempts"] == 2


async def test_cancel_skips_the_rest(clean):
    email = _who()
    job_id = await _running(email)
    await js.claim_next_step()
    assert await js.cancel(job_id, _who()) is False, "not the owner"
    assert await js.cancel(job_id, email) is True
    job = await js.get(job_id)
    assert job["status"] == "cancelled" and job["finished_at"] is not None
    assert [s["status"] for s in job["steps"]] == ["skipped"] * 3
    assert await js.cancel(job_id, email) is False, "already over"
    # A step that finishes after the Stop does not come back to life.
    assert await js.finish_step(job["steps"][0]["id"], "done", "late") is False
    assert (await js.get(job_id))["steps"][0]["status"] == "skipped"


async def test_cancel_a_proposed_plan(clean):
    email = _who()
    job_id = await _proposed(email)
    assert await js.cancel(job_id, email) is True
    assert (await js.get(job_id))["status"] == "cancelled"
    # Cancelling frees the person to start another.
    assert await js.start(await _proposed(email), email) is True


async def test_set_status_finishes_and_never_reopens_a_finished_job(clean):
    email = _who()
    job_id = await _running(email)
    assert await js.set_status(job_id, "done", result="the answer") is True
    job = await js.get(job_id)
    assert job["status"] == "done" and job["result"] == "the answer"
    assert job["finished_at"] is not None
    assert await js.set_status(job_id, "running") is False
    assert (await js.get(job_id))["status"] == "done"


async def test_a_failed_job_skips_its_waiting_steps(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.finish_step(step["id"], "failed", "it broke")
    assert await js.set_status(job_id, "failed") is True
    assert [s["status"] for s in (await js.get(job_id))["steps"]] == [
        "failed", "skipped", "skipped"]


async def test_recover_requeues_running_steps_and_expires_old_plans(clean):
    email = _who()
    running = await _running(email)
    step = await js.claim_next_step()
    old = await _proposed(_who())
    fresh = await _proposed(_who())
    async with session() as s:
        await s.execute(sql_text(
            "UPDATE tasks.agent_job SET created_at = now() - interval '25 hours' "
            "WHERE id = :id"), {"id": old})
        await s.commit()

    assert (await js.recover_after_restart())["requeued"] >= 1
    job = await js.get(running)
    assert job["status"] == "running"
    assert job["steps"][0]["status"] == "waiting"
    assert job["steps"][0]["attempts"] == 1, "the lost attempt still counts"
    again = await js.claim_next_step()
    assert again["id"] == step["id"] and again["attempts"] == 2
    assert (await js.get(old))["status"] == "cancelled"
    assert (await js.get(fresh))["status"] == "proposed"


async def test_recover_leaves_a_step_waiting_on_the_person_alone(clean):
    # A needs_you job's step is held, not lost: the person's Yes or No
    # finishes it. Requeueing it would run the step again behind their back.
    email = _who()
    job_id = await _running(email)
    await js.claim_next_step()
    await js.set_status(job_id, "needs_you")
    await js.recover_after_restart()
    assert (await js.get(job_id))["steps"][0]["status"] == "running"


async def test_unseen_badge_counts_finished_jobs_until_seen(clean):
    email = _who()
    assert await js.unseen_count(email) == 0
    job_id = await _running(email)
    assert await js.unseen_count(email) == 0, "a running job is not news yet"
    await js.set_status(job_id, "done", result="ok")
    assert await js.unseen_count(email) == 1
    assert await js.unseen_count(_who()) == 0
    await js.mark_seen(email)
    assert await js.unseen_count(email) == 0


async def test_jobs_for_chat_summarises_each_card(clean):
    email = _who()
    job_id = await _running(email)
    other_chat = await _proposed(email, chat_id="chat-2")
    step = await js.claim_next_step()
    await js.finish_step(step["id"], "done", "found them")
    await js.claim_next_step()

    cards = await js.jobs_for_chat(email, "chat-1")
    assert set(cards) == {job_id}
    assert cards[job_id] == {"status": "running", "done": 1, "total": 3,
                             "current_agent_id": "agent-ada"}
    assert set(await js.jobs_for_chat(email, "chat-2")) == {other_chat}
    assert await js.jobs_for_chat(_who(), "chat-1") == {}


async def test_a_long_request_is_cut_to_the_cap(clean):
    # The request rides in every step's brief and on the card; one pasted
    # novel must not make every one of those as large as it was.
    email = _who()
    job_id = await js.create_proposed(email, "chat-1", "agent-lead",
                                      "x" * (js.REQUEST_MAX_CHARS + 500),
                                      STEPS)
    assert len((await js.get(job_id))["request"]) == js.REQUEST_MAX_CHARS


# --- a restart never runs a step a third time, or again after it acted -------

async def _tool_ran(email: str, agent_id: str, status: str = "ok",
                    source: str = "job", ago_seconds: int = 0) -> None:
    """A run of `agent_id` for `email` that called one tool, as
    agent_activity.start_run and record_step write them."""
    run_id = str(uuid.uuid4())
    async with session() as s:
        await s.execute(sql_text(
            "INSERT INTO tasks.agent_run (id, agent_id, user_email, source, "
            "status, started_at) VALUES (:id, :agent, :email, :source, "
            "'completed', now() - make_interval(secs => :ago))"),
            {"id": run_id, "agent": agent_id, "email": email,
             "source": source, "ago": ago_seconds})
        await s.execute(sql_text(
            "INSERT INTO tasks.agent_step (id, run_id, agent_id, user_email, "
            "tool, status, finished_at) VALUES (:id, :run, :agent, :email, "
            "'send_email', :status, now())"),
            {"id": str(uuid.uuid4()), "run": run_id, "agent": agent_id,
             "email": email, "status": status})
        await s.commit()


async def _ended(recovered: dict, job_id: str) -> dict:
    (item,) = [e for e in recovered["ended"] if e["job_id"] == job_id]
    return item


async def test_recover_fails_a_step_that_has_used_its_attempts(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.requeue_step(step["id"])
    again = await js.claim_next_step()
    assert again["attempts"] == js.MAX_ATTEMPTS
    recovered = await js.recover_after_restart()
    job = await js.get(job_id)
    assert job["status"] == "failed" and job["finished_at"] is not None
    assert [s["status"] for s in job["steps"]] == ["failed", "skipped",
                                                   "skipped"]
    assert job["steps"][0]["attempts"] == js.MAX_ATTEMPTS
    item = await _ended(recovered, job_id)
    assert (item["status"], item["why"], item["agent_id"], item["position"],
            item["user_email"]) == ("failed", js.WHY_INTERRUPTED,
                                    "agent-mia", 1, email)
    assert await js.claim_next_step() is None


async def test_a_restart_never_gives_a_step_a_third_attempt(clean):
    email = _who()
    job_id = await _running(email)
    await js.claim_next_step()
    assert (await js.recover_after_restart())["requeued"] == 1
    second = await js.claim_next_step()
    assert second["attempts"] == 2
    # The process dies again during the second attempt.
    assert (await js.recover_after_restart())["requeued"] == 0
    assert await js.claim_next_step() is None
    steps = (await js.get(job_id))["steps"]
    assert steps[0]["status"] == "failed" and steps[0]["attempts"] == 2


async def test_recover_fails_a_step_whose_tools_already_ran(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    assert await js.step_acted(step["id"]) is False
    await _tool_ran(email, "agent-mia")
    assert await js.step_acted(step["id"]) is True
    recovered = await js.recover_after_restart()
    assert recovered["requeued"] == 0
    job = await js.get(job_id)
    assert job["status"] == "failed"
    assert [s["status"] for s in job["steps"]] == ["failed", "skipped",
                                                   "skipped"]
    assert job["steps"][0]["attempts"] == 1
    assert (await _ended(recovered, job_id))["why"] == js.WHY_ACTED


async def test_only_a_tool_this_step_ran_counts_as_acting(clean):
    email = _who()
    await _running(email)
    step = await js.claim_next_step()
    # Asked about, refused, or held for a yes: none of these ran.
    await _tool_ran(email, "agent-mia", status="held")
    await _tool_ran(email, "agent-mia", status="refused")
    # The person chatting with the same agent meanwhile is not the step.
    await _tool_ran(email, "agent-mia", source="channel")
    # Another agent of theirs, and the same agent before the step began.
    await _tool_ran(email, "agent-ada")
    await _tool_ran(email, "agent-mia", ago_seconds=3600)
    # Somebody else's agent with the same id.
    await _tool_ran(_who(), "agent-mia")
    assert await js.step_acted(step["id"]) is False
    # A tool that ran and failed may still have done something.
    await _tool_ran(email, "agent-mia", status="failed")
    assert await js.step_acted(step["id"]) is True


async def test_a_retry_is_judged_on_its_own_attempt(clean):
    # The claim stamps when the attempt began, so a tool from a previous
    # attempt (which was then allowed to retry because it had none) does not
    # leak forward, and a reclaim stamps afresh.
    email = _who()
    await _running(email)
    step = await js.claim_next_step()
    await js.requeue_step(step["id"])
    async with session() as s:
        await s.execute(sql_text(
            "UPDATE tasks.agent_job_step SET started_at = now() - "
            "interval '1 hour' WHERE id = :id"), {"id": step["id"]})
        await s.commit()
    await _tool_ran(email, "agent-mia", ago_seconds=1800)
    again = await js.claim_next_step()
    assert again["id"] == step["id"]
    assert await js.step_acted(step["id"]) is False


# --- the sweep: a live job with nothing left that can move it ----------------

async def _set_step(step_id: str, status: str) -> None:
    async with session() as s:
        await s.execute(sql_text(
            "UPDATE tasks.agent_job_step SET status = :st WHERE id = :id"),
            {"st": status, "id": step_id})
        await s.commit()


async def _all_done(email: str) -> str:
    job_id = await _running(email)
    for _ in range(3):
        step = await js.claim_next_step()
        await js.finish_step(step["id"], "done", "ok")
    return job_id


def _mine(ended: list[dict], job_id: str) -> list[dict]:
    return [e for e in ended if e["job_id"] == job_id]


async def test_sweep_finishes_a_running_job_whose_steps_are_all_done(clean):
    # A restart during the lead's closing turn: every result is posted and
    # nothing is left to claim, so nothing would ever move it.
    email = _who()
    job_id = await _all_done(email)
    ended = await js.sweep_stuck()
    job = await js.get(job_id)
    assert job["status"] == "done" and job["finished_at"] is not None
    (item,) = _mine(ended, job_id)
    assert (item["status"], item["why"], item["user_email"]) == (
        "done", js.WHY_NO_SUMMARY, email)
    # It no longer holds the person's one running slot.
    assert await js.start(await _proposed(email), email) is True


async def test_sweep_fails_a_running_job_with_nothing_left_to_run(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.finish_step(step["id"], "done", "ok")
    job = await js.get(job_id)
    await _set_step(job["steps"][1]["id"], "failed")
    await _set_step(job["steps"][2]["id"], "skipped")
    ended = await js.sweep_stuck()
    assert (await js.get(job_id))["status"] == "failed"
    assert _mine(ended, job_id)[0]["why"] == js.WHY_STRANDED


async def test_sweep_leaves_a_job_in_flight_alone(clean):
    email = _who()
    job_id = await _running(email)
    await js.claim_next_step()                      # a step is running
    other = _who()
    closing = await _all_done(other)                # the lead is closing it
    ended = await js.sweep_stuck(exclude_job_ids=[closing])
    assert (await js.get(job_id))["status"] == "running"
    assert (await js.get(closing))["status"] == "running"
    assert not _mine(ended, job_id) and not _mine(ended, closing)


async def test_sweep_fails_a_paused_job_with_no_question_left(clean):
    # needs_you with nothing held: the answer's own write failed half way,
    # or the question was never shown. Nobody can answer it any more.
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.set_status(job_id, "needs_you")
    await js.finish_step(step["id"], "done", "answered")
    ended = await js.sweep_stuck()
    job = await js.get(job_id)
    assert job["status"] == "failed"
    assert [s["status"] for s in job["steps"]] == ["done", "skipped",
                                                   "skipped"]
    assert _mine(ended, job_id)[0]["why"] == js.WHY_STRANDED


async def test_sweep_fails_a_question_nobody_answered_in_time(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.set_status(job_id, "needs_you")
    fresh_owner = _who()
    fresh = await _running(fresh_owner)
    await js.claim_next_step()
    await js.set_status(fresh, "needs_you")
    async with session() as s:
        await s.execute(sql_text(
            "UPDATE tasks.agent_job_step SET started_at = now() - "
            "make_interval(hours => :h) WHERE id = :id"),
            {"h": js.NEEDS_YOU_MAX_HOURS + 1, "id": step["id"]})
        await s.commit()
    ended = await js.sweep_stuck()
    job = await js.get(job_id)
    assert job["status"] == "failed"
    assert [s["status"] for s in job["steps"]] == ["failed", "skipped",
                                                   "skipped"]
    (item,) = _mine(ended, job_id)
    assert (item["why"], item["agent_id"], item["position"]) == (
        js.WHY_UNANSWERED, "agent-mia", 1)
    assert (await js.get(fresh))["status"] == "needs_you"
    assert not _mine(ended, fresh)


async def test_recover_sweeps_too(clean):
    email = _who()
    job_id = await _all_done(email)
    recovered = await js.recover_after_restart()
    assert (await js.get(job_id))["status"] == "done"
    assert _mine(recovered["ended"], job_id)[0]["why"] == js.WHY_NO_SUMMARY


async def test_finish_held_step_reopens_the_job_in_one_write(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.set_status(job_id, "needs_you")
    assert await js.finish_held_step(step["id"], job_id, "sent it",
                                     reopen=True) is True
    job = await js.get(job_id)
    assert job["status"] == "running"
    assert (job["steps"][0]["status"], job["steps"][0]["result"]) == (
        "done", "sent it")
    # Not held any more: a second answer changes nothing.
    assert await js.finish_held_step(step["id"], job_id, "again",
                                     reopen=True) is False


async def test_finish_held_step_on_the_last_step_leaves_the_job_paused(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.set_status(job_id, "needs_you")
    assert await js.finish_held_step(step["id"], job_id, "sent it",
                                     reopen=False) is True
    assert (await js.get(job_id))["status"] == "needs_you"


async def test_finish_held_step_after_stop_changes_nothing(clean):
    email = _who()
    job_id = await _running(email)
    step = await js.claim_next_step()
    await js.set_status(job_id, "needs_you")
    await js.cancel(job_id, email)
    assert await js.finish_held_step(step["id"], job_id, "late",
                                     reopen=True) is False
    job = await js.get(job_id)
    assert job["status"] == "cancelled"
    assert job["steps"][0]["status"] == "skipped"


async def test_cancel_live_stops_only_this_persons_live_job(clean):
    email = _who()
    live = await _running(email)
    await js.claim_next_step()
    proposed = await _proposed(email)
    other = _who()
    others = await _running(other)
    stopped = await js.cancel_live(email)
    assert [j["job_id"] for j in stopped] == [live]
    assert stopped[0]["lead_agent_id"] == "agent-lead"
    job = await js.get(live)
    assert job["status"] == "cancelled"
    assert [s["status"] for s in job["steps"]] == ["skipped"] * 3
    assert (await js.get(proposed))["status"] == "proposed"
    assert (await js.get(others))["status"] == "running"
    assert await js.cancel_live(email) == []
