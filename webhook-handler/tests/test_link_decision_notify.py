import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import LINK_APPROVE_PREFIX, LINK_REJECT_PREFIX, PANEL_NEW_ID


def _make_handler():
    router = MagicMock()
    router.approve_link = AsyncMock()
    router.reject_link = AsyncMock()
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.send_dm = AsyncMock(return_value=True)
    h = DiscordCommandHandler(discord_client=discord, command_router=router)
    return h, router, discord


@pytest.mark.asyncio
async def test_approve_dms_user_with_build_button():
    h, router, discord = _make_handler()
    payload = {"token": "tok", "member": {"user": {"id": "admin1", "username": "ad"}}}
    custom_id = f"{LINK_APPROVE_PREFIX}user-42"
    await h._handle_link_decision(payload, custom_id, approve=True)
    for _ in range(5):
        await asyncio.sleep(0)  # let the detached _do() task run
    router.approve_link.assert_awaited()
    discord.send_dm.assert_awaited()
    args, kwargs = discord.send_dm.call_args
    # user id is first positional
    assert (args[0] if args else kwargs.get("user_id")) == "user-42"
    sent_components = kwargs.get("components")
    assert sent_components[0]["components"][0]["custom_id"] == PANEL_NEW_ID


@pytest.mark.asyncio
async def test_reject_dms_user_and_tolerates_dm_failure():
    h, router, discord = _make_handler()
    discord.send_dm = AsyncMock(return_value=False)  # DM fails
    payload = {"token": "tok", "member": {"user": {"id": "admin1", "username": "ad"}}}
    custom_id = f"{LINK_REJECT_PREFIX}user-42"
    await h._handle_link_decision(payload, custom_id, approve=False)
    for _ in range(5):
        await asyncio.sleep(0)
    router.reject_link.assert_awaited()
    discord.send_dm.assert_awaited()  # attempted; failure tolerated, no raise
