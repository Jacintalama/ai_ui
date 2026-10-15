"""The background worker that runs a started team job's steps.

Everything outside the worker is a fake: the store, the turn runner, the
chat posting and the live feed. No model is called and no database is
touched.
"""
import asyncio

import pytest

import agent_job_worker as worker


@pytest.fixture(autouse=True)
def _fresh_worker():
    worker._RUNNING.clear()
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
