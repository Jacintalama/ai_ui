"""A flood that was capped has to leave a record, not just a log line.

Both pollers allow five firings per rule per tick and move the cursor past
the rest, deliberately: otherwise the same flood arrives again on the next
tick, for ever. Drag twenty cards into a watched list and five run.

Until now the other fifteen left nothing behind. One INFO line on the
server, which is the one place the person who was flooded cannot look, and
on the page five successful runs and no sign that anything was dropped.

That is the worst kind of missing record, because the rule looks like it
worked. STATUS_SKIPPED had been declared since 2026-10-27 and used by
nothing, which is what put me onto it.

Checked here rather than on the page, because the row is what the page
draws and the row is what was absent.
"""
import pytest

import automation_runner as ar
import email_trigger
import trello_trigger

RULE = {"id": "r1", "user_email": "ralph@example.com", "name": "Watch Review",
        "agent_id": "a1", "instructions": "Summarise it.", "trigger": "trello",
        "trigger_query": "l" * 24, "deliver_to": "chat", "hook_token": "hk_x"}


@pytest.fixture
def recorded(monkeypatch):
    rows = []

    async def record_run(email, automation_id, status, trigger_text, result,
                         delivered):
        rows.append({"email": email, "id": automation_id, "status": status,
                     "trigger": trigger_text, "result": result,
                     "delivered": delivered})

    monkeypatch.setattr(ar.automations, "record_run", record_run)
    return rows


async def test_a_capped_flood_is_recorded(recorded):
    await ar.record_skipped(RULE, 15, 5)
    assert len(recorded) == 1
    row = recorded[0]
    assert row["status"] == ar.STATUS_SKIPPED
    assert row["email"] == "ralph@example.com" and row["id"] == "r1"
    assert "15" in row["trigger"]


async def test_it_says_they_are_gone_rather_than_queued(recorded):
    """The cursor has moved past them. Somebody who reads "skipped" and
    waits for them to arrive later is waiting for nothing."""
    await ar.record_skipped(RULE, 15, 5)
    result = recorded[0]["result"].lower()
    assert "not be picked up later" in result or "moved on past" in result


async def test_the_sentence_uses_the_callers_cap(recorded):
    """Each poller owns that number. A copy here would be free to drift
    from the two that are actually enforced."""
    await ar.record_skipped(RULE, 9, 5)
    assert "Only 5 can run" in recorded[0]["result"]
    await ar.record_skipped(RULE, 9, 25)
    assert "Only 25 can run" in recorded[1]["result"]


async def test_one_row_per_tick_not_per_dropped_item(recorded):
    """Fifteen rows would bury the runs that actually happened, which are
    the ones somebody opened the page to read."""
    await ar.record_skipped(RULE, 15, 5)
    assert len(recorded) == 1


async def test_nothing_skipped_writes_nothing(recorded):
    """An ordinary tick must not leave a row saying nothing was dropped."""
    for none in (0, -1):
        await ar.record_skipped(RULE, none, 5)
    assert recorded == []


async def test_one_skipped_reads_as_one(recorded):
    await ar.record_skipped(RULE, 1, 5)
    row = recorded[0]
    assert "1 more message arrived" in row["trigger"]
    assert "1 was skipped" in row["result"]


def test_the_caps_the_pollers_enforce_are_the_ones_reported():
    """Both pollers cap at the same number today. If one changes, its own
    constant is what reaches the person, which is the point of passing it
    in rather than naming it twice."""
    assert email_trigger.BURST == 5
    assert trello_trigger.BURST == 5


def test_skipped_is_a_status_the_runner_knows():
    """It was declared and unused for a week. An unused constant is a
    feature somebody meant to build."""
    assert ar.STATUS_SKIPPED == "skipped"
    assert ar.STATUS_SKIPPED not in (ar.STATUS_DONE, ar.STATUS_FAILED,
                                     ar.STATUS_WAITING)
