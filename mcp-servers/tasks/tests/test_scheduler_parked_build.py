"""A scheduled build that was refused is reported as failed, not as queued.

Found 2026-09-18. Two schedules had been running twice a day for a week with
every run refused by the model provider for lack of credit. Nothing said so:

  * the task row parks at `status="pending"` with the reason in `result`,
    which is deliberate for the App Builder page (it offers Try again from
    there, see test_build_failure_is_visible, 2026-08-12)
  * the scheduler passed that raw status through as the RUN's status
  * Discord's formatter labels anything that is not completed or skipped with
    the raw status, so the owner got a daily warning headed PENDING
  * the Cron page maps `pending` to the QUEUED badge

So both surfaces showed a dead schedule as one that was waiting to run. The
scheduler creates the row and runs it synchronously, so a row still at
`pending` when that call returns did not succeed.
"""
import types

import pytest

import scheduler


def _row(status, result=""):
    return types.SimpleNamespace(status=status, result=result)


def _execution(log=""):
    return types.SimpleNamespace(log=log)


@pytest.mark.parametrize("parked_result", [
    "Previous AI run failed: API Error: 402 This request requires more credits",
    "The build did not finish.",
    "",
])
def test_a_parked_build_is_a_failed_run(parked_result):
    """Whatever the reason reads like. The status is the claim being fixed,
    and a reason this code has not seen before must not make it pass."""
    status = scheduler._run_status_for(_row("pending", parked_result))
    assert status == "failed"


def test_a_completed_build_is_left_alone():
    assert scheduler._run_status_for(_row("completed", "done")) == "completed"


@pytest.mark.parametrize("status", ["awaiting_input", "claimed_manual",
                                    "running"])
def test_every_other_status_passes_through_untouched(status):
    """Only `pending` is being reinterpreted. A build waiting on a question is
    genuinely waiting, and calling that a failure would be the same kind of
    lie in the other direction."""
    assert scheduler._run_status_for(_row(status)) == status


def test_a_row_that_vanished_is_unknown_not_failed():
    """The row is re-read after the run. If it is gone, something else
    happened and inventing "failed" would put a reason in the owner's thread
    that nobody established."""
    assert scheduler._run_status_for(None) == "unknown"


def test_a_blank_status_is_unknown():
    assert scheduler._run_status_for(_row("")) == "unknown"
