"""tool_mode has to survive the whole round trip.

Every assertion here exists because the neighbouring column, agent_id, was
lost twice on this feature: once in the insert and once in the serializer,
each time with a full green suite.
"""
from fastapi import HTTPException

import pytest

import routes_schedules
from routes_schedules import CreateScheduleIn, _serialize


def test_the_request_model_accepts_a_tool_mode():
    body = CreateScheduleIn(
        user_email="owner@example.com", name="n", cron_expr="0 9 * * *",
        tz="Asia/Manila", prompt="p", tool_mode="full")
    assert body.tool_mode == "full"


def test_tool_mode_defaults_to_none_so_existing_callers_are_unchanged():
    body = CreateScheduleIn(
        user_email="owner@example.com", name="n", cron_expr="0 9 * * *",
        tz="Asia/Manila", prompt="p")
    assert body.tool_mode is None


async def test_an_unrecognised_tool_mode_is_rejected_with_400():
    """F8: the request model accepts any string -- "ask" and "Full" store
    happily today, and act as read_only only because agent_runner's own
    check happens to be fail-closed. That is not the same as the endpoint
    rejecting them. Validating here closes the gap where a typo, or a value
    written before this check existed, silently becomes something other
    than what the owner actually chose."""
    body = CreateScheduleIn(
        user_email="owner@example.com", name="n", cron_expr="0 9 * * *",
        tz="Asia/Manila", prompt="p", tool_mode="ask")

    with pytest.raises(HTTPException) as exc_info:
        await routes_schedules.create_schedule(
            body=body, x_cron_secret="", x_user_email="owner@example.com",
            x_user_admin="")

    assert exc_info.value.status_code == 400


def test_serialize_returns_the_tool_mode():
    """Deleting this line must fail a test. Last time the equivalent line
    for agent_id was removed, all 31 tests still passed."""
    class _Sched:
        id = "11111111-1111-1111-1111-111111111111"
        user_email = "owner@example.com"
        name = "n"
        cron_expr = "0 9 * * *"
        tz = "Asia/Manila"
        persona = None
        prompt = "p"
        enabled = True
        run_once = False
        delivery_channel_id = None
        delivery_platform = None
        kind = "agent"
        video_config = None
        agent_id = "agent-x-0001"
        tool_mode = "full"
        last_run_at = None
        last_run_status = None
        last_result = None
        last_result_at = None
        created_at = None

    out = _serialize(_Sched())
    assert out["tool_mode"] == "full"


async def test_the_insert_actually_carries_tool_mode_and_agent_id(monkeypatch):
    """The value the caller sent has to reach the row that gets written.

    This is not a hypothetical. The neighbouring column agent_id was accepted
    by this same endpoint and silently dropped by this same insert, so
    schedules were created with no agent and nothing failed anywhere. Every
    other test here passes with `tool_mode=body.tool_mode` deleted from the
    insert, so without this one that bug is free to happen again.

    Captures the Schedule handed to session.add rather than reaching a
    database, so it runs in the ordinary tier.
    """
    import routes_schedules

    added = []

    class _FakeResult:
        # The handler counts existing schedules before inserting; this stands
        # in for that query without needing a database.
        def scalar(self):
            return 0

        def scalar_one(self):
            return 0

        def scalar_one_or_none(self):
            return 0

        def scalars(self):
            return self

        def all(self):
            return []

    class _FakeSession:
        def add(self, obj):
            added.append(obj)

        async def execute(self, *a, **kw):
            return _FakeResult()

        async def commit(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(routes_schedules, "session", lambda: _FakeSession())

    body = CreateScheduleIn(
        user_email="owner@example.com", name="n", cron_expr="0 9 * * *",
        tz="Asia/Manila", prompt="p", agent_id="agent-x-0001",
        tool_mode="full")

    await routes_schedules.create_schedule(
        body=body, x_cron_secret="", x_user_email="owner@example.com",
        x_user_admin="")

    assert len(added) == 1, "the handler did not write a row"
    written = added[0]
    assert written.tool_mode == "full", "tool_mode never reached the insert"
    assert written.agent_id == "agent-x-0001", "agent_id never reached the insert"
