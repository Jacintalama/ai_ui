"""Routing: Open my schedules → private thread + dashboard; dropdown → card."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import SCHED_OPEN_ID, SCHED_SELECT_ID


def _handler(router):
    d = MagicMock()
    d.edit_original = AsyncMock(return_value=True)
    d.post_channel_message = AsyncMock(return_value=True)
    d.create_private_thread = AsyncMock(return_value="thread-9")
    d.add_thread_member = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=d, command_router=router)


def _component(custom_id, user_id="100"):
    return {"type": 3, "id": "i", "token": "t", "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "alice"}}, "channel_id": "c"}


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_open_posts_dashboard_to_existing_thread():
    router = MagicMock()
    router.dashboard_payload = AsyncMock(return_value={"content": "📅 Your schedules", "components": []})
    router.get_user_thread = AsyncMock(return_value="t9")
    handler = _handler(router)
    resp = await handler.handle_interaction(_component(SCHED_OPEN_ID))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    args, kwargs = handler.discord.post_channel_message.call_args
    assert args[0] == "t9"
    handler.discord.edit_original.assert_awaited()


@pytest.mark.asyncio
async def test_open_creates_thread_when_none():
    router = MagicMock()
    router.dashboard_payload = AsyncMock(return_value={"content": "x", "components": []})
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock(return_value=True)
    handler = _handler(router)
    await handler.handle_interaction(_component(SCHED_OPEN_ID))
    await _drain()
    handler.discord.create_private_thread.assert_awaited()
    router.set_user_thread.assert_awaited_once_with("100", "thread-9")
    assert handler.discord.post_channel_message.call_args[0][0] == "thread-9"


@pytest.mark.asyncio
async def test_open_not_linked_prompts_link():
    router = MagicMock()
    router.dashboard_payload = AsyncMock(return_value=None)
    handler = _handler(router)
    await handler.handle_interaction(_component(SCHED_OPEN_ID))
    await _drain()
    handler.discord.post_channel_message.assert_not_called()
    handler.discord.edit_original.assert_awaited()


@pytest.mark.asyncio
async def test_select_routes_to_card():
    calls = []

    async def fake_card(ctx, sid):
        calls.append((ctx.user_id, sid))
    router = MagicMock()
    router.run_schedule_card = fake_card
    handler = _handler(router)
    payload = {"type": 3, "id": "i", "token": "t",
               "data": {"custom_id": SCHED_SELECT_ID, "values": ["s1"]},
               "member": {"user": {"id": "100", "username": "alice"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    assert calls == [("100", "s1")]
