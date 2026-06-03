import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import PANEL_NEW_ID, TEMPLATE_SELECT_ID


def _payload(custom_id, user_id="U1"):
    return {"type": 3, "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "maya"}},
            "channel_id": "C1", "token": "tok"}


@pytest.mark.asyncio
async def test_build_new_posts_template_picker_to_thread():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="THREAD1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock()
    router._resolve_email_auto = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(
        return_value=[{"key": "portfolio", "label": "Portfolio"}])
    h = DiscordCommandHandler(discord, router)
    resp = await h.handle_interaction(_payload(PANEL_NEW_ID))
    await asyncio.sleep(0)
    args = discord.post_channel_message.await_args
    assert args.args[0] == "THREAD1"
    comps = args.kwargs.get("components") or (args.args[2] if len(args.args) > 2 else [])
    flat = [c for row in comps for c in row["components"]]
    assert any(c.get("custom_id") == TEMPLATE_SELECT_ID for c in flat)


@pytest.mark.asyncio
async def test_build_new_returns_deferred_ephemeral():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="THREAD1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock()
    router._resolve_email_auto = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(return_value=[])
    h = DiscordCommandHandler(discord, router)
    resp = await h.handle_interaction(_payload(PANEL_NEW_ID))
    assert resp["type"] == 5
    assert resp["data"]["flags"] == 64
