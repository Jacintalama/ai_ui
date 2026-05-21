"""DiscordCommandHandler: button click -> modal, modal submit -> build."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_INPUT_ID, PUBLISH_PREFIX
from handlers.app_builder_panel import ENHANCE_PREFIX, UNPUBLISH_PREFIX, ENHANCE_MODAL_PREFIX


def _handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=discord, command_router=router)


@pytest.mark.asyncio
async def test_button_click_opens_modal():
    handler = _handler(MagicMock())
    payload = {
        "type": 3, "id": "i", "token": "t",
        "data": {"custom_id": f"{TEMPLATE_PREFIX}portfolio"},
        "member": {"user": {"id": "100", "username": "t"}},
        "channel_id": "c",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == f"{BUILD_PREFIX}portfolio"


@pytest.mark.asyncio
async def test_unknown_component_is_noop():
    handler = _handler(MagicMock())
    resp = await handler.handle_interaction({"type": 3, "data": {"custom_id": "something:else"}})
    assert resp["type"] == 6  # DEFERRED_UPDATE_MESSAGE, never an error


@pytest.mark.asyncio
async def test_modal_submit_routes_build():
    captured = {}
    async def fake_run(ctx, template_key, description):
        captured.update(ctx=ctx, key=template_key, desc=description)
    router = MagicMock(); router.run_panel_build = fake_run
    handler = _handler(router)
    payload = {
        "type": 5, "id": "i", "token": "tok",
        "data": {
            "custom_id": f"{BUILD_PREFIX}portfolio",
            "components": [{"type": 1, "components": [
                {"type": 4, "custom_id": DESCRIPTION_INPUT_ID, "value": "a portfolio for Maya"}]}],
        },
        "member": {"user": {"id": "100", "username": "maya"}},
        "channel_id": "chan-1",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5  # deferred ACK
    await asyncio.sleep(0)
    assert captured["key"] == "portfolio"
    assert captured["desc"] == "a portfolio for Maya"
    assert captured["ctx"].user_id == "100"
    assert captured["ctx"].notify_channel is not None


@pytest.mark.asyncio
async def test_modal_submit_blank_key():
    captured = {}
    async def fake_run(ctx, template_key, description):
        captured["key"] = template_key
    router = MagicMock(); router.run_panel_build = fake_run
    handler = _handler(router)
    payload = {
        "type": 5, "token": "tok",
        "data": {
            "custom_id": BUILD_PREFIX,
            "components": [{"type": 1, "components": [
                {"type": 4, "custom_id": DESCRIPTION_INPUT_ID, "value": "a blank app"}]}],
        },
        "member": {"user": {"id": "100", "username": "x"}},
        "channel_id": "c",
    }
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    assert captured["key"] is None


@pytest.mark.asyncio
async def test_publish_button_routes_publish():
    captured = {}
    async def fake_pub(ctx, slug):
        captured.update(ctx=ctx, slug=slug)
    router = MagicMock(); router.run_panel_publish = fake_pub
    handler = _handler(router)
    payload = {
        "type": 3, "id": "i", "token": "tok",
        "data": {"custom_id": f"{PUBLISH_PREFIX}portfolio-ab12"},
        "member": {"user": {"id": "100", "username": "maya"}},
        "channel_id": "chan-1",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5  # deferred ACK
    await asyncio.sleep(0)
    assert captured["slug"] == "portfolio-ab12"
    assert captured["ctx"].user_id == "100"


@pytest.mark.asyncio
async def test_malformed_publish_button_is_noop():
    handler = _handler(MagicMock())
    resp = await handler.handle_interaction({"type": 3, "data": {"custom_id": "aiuibuild:publish:"}})
    assert resp["type"] == 6  # DEFERRED_UPDATE_MESSAGE, no 500


@pytest.mark.asyncio
async def test_enhance_button_opens_modal():
    handler = _handler(MagicMock())
    payload = {"type": 3, "id": "i", "token": "t",
               "data": {"custom_id": f"{ENHANCE_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9
    assert resp["data"]["custom_id"] == f"{ENHANCE_MODAL_PREFIX}slug-1"


@pytest.mark.asyncio
async def test_unpublish_button_routes():
    captured = {}
    async def fake_unpub(ctx, slug): captured["slug"] = slug
    router = MagicMock(); router.run_panel_unpublish = fake_unpub
    handler = _handler(router)
    payload = {"type": 3, "id": "i", "token": "tok",
               "data": {"custom_id": f"{UNPUBLISH_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)
    assert captured["slug"] == "slug-1"


@pytest.mark.asyncio
async def test_enhance_modal_submit_routes():
    captured = {}
    async def fake_enh(ctx, slug, prompt): captured.update(slug=slug, prompt=prompt)
    router = MagicMock(); router.run_panel_enhance = fake_enh
    handler = _handler(router)
    payload = {"type": 5, "id": "i", "token": "tok",
               "data": {"custom_id": f"{ENHANCE_MODAL_PREFIX}slug-1",
                        "components": [{"type": 1, "components": [
                            {"type": 4, "custom_id": "change", "value": "make it blue"}]}]},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)
    assert captured == {"slug": "slug-1", "prompt": "make it blue"}
