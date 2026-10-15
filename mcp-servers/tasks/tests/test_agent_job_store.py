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
        await s.execute(sql_text(
            "DELETE FROM tasks.agent_job WHERE user_email LIKE :p"),
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

    assert await js.recover_after_restart() >= 1
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
