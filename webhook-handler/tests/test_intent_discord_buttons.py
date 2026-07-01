"""Discord button routing for the intent-router confirm/cancel buttons.

Mirrors the _handler/payload pattern in test_app_builder_interactions.py:
a type-3 (message component) interaction with our aiuiintent:* custom_id
must reach the router's run_confirmed_intent / answer_intent."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers import intent_cards


def _handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=discord, command_router=router)


def _component_payload(custom_id):
    return {
        "type": 3, "id": "i", "token": "tok",
        "data": {"custom_id": custom_id},
        "member": {"user": {"id": "100", "username": "x"}},
        "channel_id": "c",
    }


async def test_intent_confirm_button_runs_confirmed_intent():
    router = MagicMock()
    # A non-thread intent (daily_briefing) takes the direct run path, not the
    # build/schedule private-thread route (which needs thread mocks).
    router.peek_intent = AsyncMock(return_value={"intent": "daily_briefing"})
    router.run_confirmed_intent = AsyncMock()
    handler = _handler(router)
    resp = await handler.handle_interaction(
        _component_payload(intent_cards.INTENT_CONFIRM_PREFIX + "tok1"))
    assert resp["type"] == 5  # deferred ephemeral ACK
    await asyncio.sleep(0)
    router.run_confirmed_intent.assert_awaited_once()


async def test_intent_cancel_button_runs_answer_intent():
    router = MagicMock()
    router.answer_intent = AsyncMock()
    handler = _handler(router)
    await handler.handle_interaction(
        _component_payload(intent_cards.INTENT_CANCEL_PREFIX + "tok1"))
    await asyncio.sleep(0)
    router.answer_intent.assert_awaited_once()


async def test_intent_confirm_build_opens_private_thread():
    """A confirmed build opens/reuses the user's private builder thread and runs
    there, so the result is delivered (the fix for the broken inline build)."""
    router = MagicMock()
    router.peek_intent = AsyncMock(return_value={"intent": "build_app", "detail": "a site"})
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
    router.run_confirmed_intent = AsyncMock()
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    discord.create_private_thread = AsyncMock(return_value="T1")
    discord.add_thread_member = AsyncMock(return_value=True)
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)
    resp = await handler.handle_interaction(
        _component_payload(intent_cards.INTENT_CONFIRM_PREFIX + "tok1"))
    assert resp["type"] == 5  # deferred ephemeral ACK
    for _ in range(12):
        await asyncio.sleep(0)
    discord.create_private_thread.assert_awaited()      # private thread opened
    router.run_confirmed_intent.assert_awaited_once()   # build runs in it
