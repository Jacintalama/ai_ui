"""Sub-project 3 (proactive daily assistant): /aiui briefing sets up / tears
down a daily-briefing schedule via the existing schedule machinery."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import (
    CommandRouter, CommandContext, daily_briefing_prompt,
    DAILY_BRIEFING_NAME, DAILY_BRIEFING_CRON,
)


def _ctx(captured, *, arguments=""):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id="100", user_name="t", channel_id="c1", raw_text="briefing",
        subcommand="briefing", arguments=arguments, platform="discord",
        respond=respond, metadata={},
    )


def _router(tc):
    if not isinstance(getattr(tc, "resolve_link", None), AsyncMock):
        tc.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map={"100": "a@x.com"}, tasks_client=tc,
    )


def test_prompt_mentions_email_and_today():
    p = daily_briefing_prompt().lower()
    assert "email" in p and "today" in p


@pytest.mark.asyncio
async def test_create_daily_briefing_creates_schedule():
    captured = []
    tc = MagicMock()
    tc.create_schedule = AsyncMock(return_value={"id": "s1"})
    await _router(tc).create_daily_briefing(_ctx(captured))
    tc.create_schedule.assert_awaited_once()
    kw = tc.create_schedule.call_args.kwargs
    assert kw["name"] == DAILY_BRIEFING_NAME
    assert kw["cron"] == DAILY_BRIEFING_CRON
    assert kw["delivery_channel_id"] == "c1"
    assert kw["delivery_platform"] == "discord"
    assert any("daily briefing" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_briefing_command_default_creates():
    captured = []
    tc = MagicMock()
    tc.create_schedule = AsyncMock(return_value={"id": "s1"})
    await _router(tc)._handle_briefing(_ctx(captured, arguments=""))
    tc.create_schedule.assert_awaited_once()


@pytest.mark.asyncio
async def test_briefing_off_removes_named_schedule():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "s1", "name": DAILY_BRIEFING_NAME},
        {"id": "s2", "name": "Something else"},
    ])
    tc.delete_schedule = AsyncMock(return_value=True)
    await _router(tc)._handle_briefing(_ctx(captured, arguments="off"))
    tc.delete_schedule.assert_awaited_once_with("a@x.com", "s1")
    assert any("turned off" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_briefing_off_when_none_exists():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[{"id": "s2", "name": "Other"}])
    tc.delete_schedule = AsyncMock()
    await _router(tc)._handle_briefing(_ctx(captured, arguments="off"))
    tc.delete_schedule.assert_not_awaited()
    assert any("don't have" in m.lower() for m in captured)
