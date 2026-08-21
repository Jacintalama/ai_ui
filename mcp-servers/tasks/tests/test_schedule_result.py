"""What a scheduled run produced, kept.

A schedule ran the agent, produced an answer, and then scheduler.py did this:

    delivery_channel = getattr(sched, "delivery_channel_id", None)
    if delivery_channel:
        await _deliver_result(...)

No channel meant the answer was discarded. The row still recorded
last_run_status='completed', so the card said "Completed" and the user got
nothing, having spent a real agent run to produce it. Every schedule created
from the web page is in exactly that state, because that form has never had a
destination to set.

Keeping the result fixes it at the root: a schedule becomes useful with no
Discord and no Slack at all, and delivery becomes a way to ALSO push it
somewhere rather than the only way to ever see it.

Two things matter about what gets stored. Agent output can carry a token it was
handed or echoed, and it goes into a database row and then onto a page, so it
is scrubbed on the way in. And it can be enormous, so it is bounded, visibly.
"""
import pytest

from scheduler import RESULT_LIMIT, result_for_storage


def test_a_normal_result_is_kept_as_it_is():
    assert result_for_storage("Here are today's three headlines.") == \
        "Here are today's three headlines."


@pytest.mark.parametrize("empty", [None, "", "   ", "\n\n"])
def test_a_run_that_said_nothing_stores_nothing(empty):
    """None rather than an empty string, so the card can tell "no result yet"
    from "the run produced an empty answer"."""
    assert result_for_storage(empty) is None


def test_a_huge_result_is_cut_and_says_so():
    """Agent output is unbounded. A card is not, and neither is a row worth
    filling with 200KB of transcript."""
    stored = result_for_storage("x" * (RESULT_LIMIT * 3))
    assert len(stored) <= RESULT_LIMIT + 80
    assert "truncated" in stored.lower()


def test_a_result_exactly_at_the_limit_is_not_marked_truncated():
    stored = result_for_storage("y" * RESULT_LIMIT)
    assert "truncated" not in stored.lower()


def test_a_secret_in_the_output_does_not_reach_the_row():
    """The run's own prompt can hand the agent a credential, and models repeat
    what they were given. This lands in a database row and then on a page."""
    stored = result_for_storage(
        "I used the key sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF to call it.")
    assert "sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF" not in stored


def test_scrubbing_does_not_mangle_ordinary_text():
    text = "Sales were up 12% and the top account is Acme Corp."
    assert result_for_storage(text) == text


# --- the wiring, which is the actual bug ----------------------------------
# result_for_storage being correct proves nothing if _finalize_run never calls
# it. That is precisely the shape of the defect being fixed: the result was
# computed correctly and then dropped. Removing the storage line passed every
# test above, so the write itself is asserted here.

import scheduler


class _FakeSession:
    """Enough of an async session to capture what a run tried to persist."""

    def __init__(self, captured):
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        # SQLAlchemy keeps an update()'s SET clause here.
        values = getattr(stmt, "_values", None) or {}
        self.captured.append({str(k): getattr(v, "value", v)
                              for k, v in values.items()})

    async def commit(self):
        pass


@pytest.fixture
def captured_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(scheduler, "session", lambda: _FakeSession(writes))

    async def _no_delivery(*a, **k):
        return None

    monkeypatch.setattr(scheduler, "_deliver_result", _no_delivery)
    return writes


class _Sched:
    id = "11111111-1111-1111-1111-111111111111"
    name = "nightly headlines"
    delivery_channel_id = None          # the case that used to lose the result
    delivery_platform = ""


async def test_a_run_with_nowhere_to_deliver_still_records_its_result(
        captured_writes, monkeypatch):
    async def _ran(sched):
        return "completed", "Here are today's three headlines.", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())

    stored = [w for w in captured_writes if any("last_result" in k for k in w)]
    assert stored, "the run's result was never written to the row"
    row = stored[0]
    assert any("three headlines" in str(v) for v in row.values())


async def test_the_status_is_still_recorded_alongside_it(captured_writes,
                                                         monkeypatch):
    async def _ran(sched):
        return "completed", "anything", {}

    monkeypatch.setattr(scheduler, "_run_scheduled_task", _ran)
    await scheduler._finalize_run(_Sched())
    assert any(any("last_run_status" in k for k in w) for w in captured_writes)
