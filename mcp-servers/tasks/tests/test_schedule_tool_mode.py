"""tool_mode has to survive the whole round trip.

Every assertion here exists because the neighbouring column, agent_id, was
lost twice on this feature: once in the insert and once in the serializer,
each time with a full green suite.
"""
import pytest

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
