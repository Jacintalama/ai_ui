import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter
from handlers.app_builder_panel import LINK_START_ID


def _ctx(platform, with_components):
    ctx = MagicMock()
    ctx.platform = platform
    ctx.respond = AsyncMock()
    ctx.respond_components = AsyncMock() if with_components else None
    return ctx


def _router():
    return CommandRouter.__new__(CommandRouter)  # bypass __init__; only helper used


@pytest.mark.asyncio
async def test_discord_not_linked_renders_link_button():
    r = _router()
    ctx = _ctx("discord", with_components=True)
    await r._respond_not_linked(ctx)
    ctx.respond_components.assert_awaited()
    text, components = ctx.respond_components.call_args.args[:2]
    assert "Lukas" not in text
    assert components[0]["components"][0]["custom_id"] == LINK_START_ID


@pytest.mark.asyncio
async def test_discord_not_linked_falls_back_to_text_without_components():
    r = _router()
    ctx = _ctx("discord", with_components=False)
    await r._respond_not_linked(ctx)
    ctx.respond.assert_awaited()
    assert "Lukas" not in ctx.respond.call_args.args[0]


@pytest.mark.asyncio
async def test_slack_not_linked_is_plain_language():
    r = _router()
    ctx = _ctx("slack", with_components=False)
    await r._respond_not_linked(ctx)
    ctx.respond.assert_awaited()
    msg = ctx.respond.call_args.args[0]
    assert "Lukas" not in msg
    assert "email access" in msg.lower()
