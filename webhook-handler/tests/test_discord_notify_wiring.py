"""DiscordCommandHandler wires ctx.notify_channel → post_channel_message."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler


@pytest.mark.asyncio
async def test_notify_channel_posts_to_channel(monkeypatch):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)

    captured_ctx = {}
    async def fake_execute(ctx):
        captured_ctx["ctx"] = ctx
    router = MagicMock()
    router.execute = fake_execute

    handler = DiscordCommandHandler(discord_client=discord, command_router=router)
    payload = {
        "type": 2, "id": "i1", "token": "tok",
        "data": {"name": "aiui", "options": [
            {"name": "aiuibuilder", "type": 1,
             "options": [{"name": "args", "type": 3, "value": 'build "x"'}]}]},
        "member": {"user": {"id": "100", "username": "tester"}},
        "channel_id": "chan-123",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)

    ctx = captured_ctx["ctx"]
    assert ctx.notify_channel is not None
    assert ctx.notify_channel_rich is not None
    await ctx.notify_channel("hello")
    discord.post_channel_message.assert_awaited_once_with("chan-123", "hello")


@pytest.mark.asyncio
async def test_notify_channel_none_without_channel():
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    captured_ctx = {}
    async def fake_execute(ctx):
        captured_ctx["ctx"] = ctx
    router = MagicMock(); router.execute = fake_execute
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)
    payload = {
        "type": 2, "id": "i1", "token": "tok",
        "data": {"name": "aiui", "options": [
            {"name": "status", "type": 1, "options": []}]},
        "member": {"user": {"id": "100", "username": "t"}},
        # no channel_id
    }
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    assert captured_ctx["ctx"].notify_channel is None
    assert captured_ctx["ctx"].notify_channel_rich is None
