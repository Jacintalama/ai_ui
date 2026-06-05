import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter
from handlers.app_builder_panel import PANEL_NEW_ID


def test_help_text_leads_with_build_and_schedule_not_dev_jargon():
    text = CommandRouter._help_text()
    head = text[:400].lower()
    assert "build an app" in head
    assert "schedule" in head
    assert "owasp" not in head
    assert "pr-review" not in head


@pytest.mark.asyncio
async def test_handle_help_renders_welcome_buttons_on_discord():
    r = CommandRouter.__new__(CommandRouter)
    ctx = MagicMock()
    ctx.platform = "discord"
    ctx.respond = AsyncMock()
    ctx.respond_components = AsyncMock()
    await r._handle_help(ctx)
    ctx.respond_components.assert_awaited()
    _text, components = ctx.respond_components.call_args.args[:2]
    ids = [c["custom_id"] for c in components[0]["components"]]
    assert PANEL_NEW_ID in ids


@pytest.mark.asyncio
async def test_handle_help_plain_text_when_no_components():
    r = CommandRouter.__new__(CommandRouter)
    ctx = MagicMock()
    ctx.platform = "slack"
    ctx.respond = AsyncMock()
    ctx.respond_components = None
    await r._handle_help(ctx)
    ctx.respond.assert_awaited()
