"""CommandRouter: dashboard_payload, run_schedule_card, thread passthroughs."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext


def _ctx(user_id):
    cap = {"text": [], "components": []}

    async def respond(msg):
        cap["text"].append(msg)

    async def respond_components(msg, comps):
        cap["components"].append((msg, comps))

    ctx = CommandContext(
        user_id=user_id, user_name="t", channel_id="c", raw_text="",
        subcommand="aiuibuilder", arguments="", platform="discord",
        respond=respond, respond_components=respond_components, metadata={})
    return ctx, cap


def _router(mapping, tc):
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping, tasks_client=tc)


@pytest.mark.asyncio
async def test_dashboard_payload_linked_with_schedules():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "s1", "cron_expr": "*/5 * * * *", "prompt": "summarize emails",
         "enabled": True, "last_run_status": None}])
    out = await _router({"100": "a@x.com"}, tc).dashboard_payload("100")
    assert out is not None
    ids = {b.get("custom_id") for row in out["components"] for b in row.get("components", [])}
    assert "aiuisched:new" in ids and "aiuisched:select" in ids


@pytest.mark.asyncio
async def test_dashboard_payload_not_linked_returns_none():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    assert await _router({}, tc).dashboard_payload("999") is None


@pytest.mark.asyncio
async def test_run_schedule_card_found_renders_card():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "s1", "cron_expr": "*/5 * * * *", "prompt": "summarize emails",
         "enabled": True, "last_run_status": None}])
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_card(ctx, "s1")
    assert cap["components"], "should render a card"
    content, comps = cap["components"][0]
    assert "summarize emails" in content
    ids = {b["custom_id"] for row in comps for b in row["components"]}
    assert "aiuisched:run:s1" in ids


@pytest.mark.asyncio
async def test_run_schedule_card_not_found_text():
    tc = MagicMock(); tc.resolve_link = AsyncMock(return_value=None)
    tc.list_schedules = AsyncMock(return_value=[])
    ctx, cap = _ctx("100")
    await _router({"100": "a@x.com"}, tc).run_schedule_card(ctx, "ghost")
    assert cap["text"] and "find" in cap["text"][0].lower()


@pytest.mark.asyncio
async def test_thread_passthroughs():
    tc = MagicMock()
    tc.get_user_thread = AsyncMock(return_value="t9")
    tc.set_user_thread = AsyncMock(return_value=True)
    r = _router({}, tc)
    assert await r.get_user_thread("100") == "t9"
    assert await r.set_user_thread("100", "t9") is True
    tc.get_user_thread.assert_awaited_once_with("100")
    tc.set_user_thread.assert_awaited_once_with("100", "t9")
