"""DiscordCommandHandler: button click -> modal, modal submit -> build."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_INPUT_ID, PUBLISH_PREFIX, TEMPLATE_SELECT_ID
from handlers.app_builder_panel import ENHANCE_PREFIX, UNPUBLISH_PREFIX, ENHANCE_MODAL_PREFIX


@pytest.mark.asyncio
async def test_template_dropdown_select_opens_build_modal():
    handler = _handler(MagicMock())
    payload = {
        "type": 3, "id": "i", "token": "t",
        "data": {"custom_id": TEMPLATE_SELECT_ID, "values": ["portfolio"]},
        "member": {"user": {"id": "100", "username": "a"}}, "channel_id": "c",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == f"{BUILD_PREFIX}portfolio"


def _handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    discord.create_private_thread = AsyncMock(return_value=None)
    discord.add_thread_member = AsyncMock(return_value=True)
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
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
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
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
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


@pytest.mark.asyncio
async def test_publish_on_published_edits_with_buttons():
    captured = {}
    async def fake_pub(ctx, slug):
        captured["ctx"] = ctx
    router = MagicMock(); router.run_panel_publish = fake_pub
    handler = _handler(router)
    payload = {"type": 3, "id": "i", "token": "tok",
               "data": {"custom_id": f"{PUBLISH_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    ctx = captured["ctx"]
    assert ctx.on_published is not None
    await ctx.on_published("https://slug-1.ai-ui.coolestdomain.win/")
    call = handler.discord.edit_original.await_args
    assert call.kwargs.get("components") is not None


def _modal_payload(custom_id, value="a portfolio"):
    return {"type": 5, "id": "i", "token": "tok",
            "data": {"custom_id": custom_id,
                     "components": [{"type": 1, "components": [
                         {"type": 4, "custom_id": DESCRIPTION_INPUT_ID, "value": value}]}]},
            "member": {"user": {"id": "100", "username": "ralph"}}, "channel_id": "main-chan"}


@pytest.mark.asyncio
async def test_build_modal_opens_private_thread_and_is_ephemeral():
    captured = {}
    async def fake_build(ctx, key, desc):
        captured["ctx"] = ctx
    router = MagicMock(); router.run_panel_build = fake_build
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="thread-9")
    discord.add_thread_member = AsyncMock(return_value=True)
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    from handlers.discord_commands import DiscordCommandHandler
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)

    resp = await handler.handle_interaction(_modal_payload(f"{BUILD_PREFIX}portfolio"))
    assert resp["type"] == 5
    assert resp["data"]["flags"] == 64
    await asyncio.sleep(0.05)

    discord.create_private_thread.assert_awaited_once()
    args = discord.create_private_thread.await_args.args
    assert args[0] == "main-chan"
    assert "ralph" in args[1]
    discord.add_thread_member.assert_awaited_once_with("thread-9", "100")
    ctx = captured["ctx"]
    await ctx.notify_channel("hi")
    discord.post_channel_message.assert_awaited_with("thread-9", "hi")


@pytest.mark.asyncio
async def test_build_modal_falls_back_to_channel_when_thread_fails():
    captured = {}
    async def fake_build(ctx, key, desc):
        captured["ctx"] = ctx
    router = MagicMock(); router.run_panel_build = fake_build
    router.get_user_builder_thread = AsyncMock(return_value=None)
    router.set_user_builder_thread = AsyncMock()
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value=None)
    discord.add_thread_member = AsyncMock(return_value=True)
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    from handlers.discord_commands import DiscordCommandHandler
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)

    resp = await handler.handle_interaction(_modal_payload(f"{BUILD_PREFIX}"))
    assert resp["type"] == 5
    await asyncio.sleep(0.05)

    discord.add_thread_member.assert_not_awaited()
    ctx = captured["ctx"]
    await ctx.notify_channel("hi")
    discord.post_channel_message.assert_awaited_with("main-chan", "hi")


# --- Delete (with confirm) flow ---
from handlers.app_builder_panel import (
    DELETE_PREFIX, DEL_CONFIRM_PREFIX, DEL_CANCEL_PREFIX,
)


@pytest.mark.asyncio
async def test_delete_button_shows_confirm_card():
    handler = _handler(MagicMock())
    payload = {"type": 3, "id": "i", "token": "tok",
               "data": {"custom_id": f"{DELETE_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    # Confirm card rendered synchronously (ephemeral message), not a delete.
    assert resp["type"] in (4, 7)
    ids = [c["custom_id"] for row in resp["data"]["components"]
           for c in row["components"]]
    assert f"{DEL_CONFIRM_PREFIX}slug-1" in ids
    assert f"{DEL_CANCEL_PREFIX}slug-1" in ids


@pytest.mark.asyncio
async def test_delete_button_malformed_is_noop():
    handler = _handler(MagicMock())
    resp = await handler.handle_interaction(
        {"type": 3, "data": {"custom_id": f"{DELETE_PREFIX}"}})
    assert resp["type"] == 6  # DEFERRED_UPDATE_MESSAGE, no 500


@pytest.mark.asyncio
async def test_del_confirm_routes_to_run_panel_delete():
    captured = {}
    async def fake_delete(ctx, slug): captured["slug"] = slug
    router = MagicMock(); router.run_panel_delete = fake_delete
    handler = _handler(router)
    payload = {"type": 3, "id": "i", "token": "tok",
               "data": {"custom_id": f"{DEL_CONFIRM_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5
    await asyncio.sleep(0)
    assert captured["slug"] == "slug-1"


@pytest.mark.asyncio
async def test_del_cancel_does_not_delete():
    router = MagicMock()
    router.run_panel_delete = AsyncMock()
    handler = _handler(router)
    payload = {"type": 3, "id": "i", "token": "tok",
               "data": {"custom_id": f"{DEL_CANCEL_PREFIX}slug-1"},
               "member": {"user": {"id": "100", "username": "u"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 7  # UPDATE_MESSAGE — "Cancelled."
    assert "cancel" in resp["data"]["content"].lower()
    await asyncio.sleep(0)
    router.run_panel_delete.assert_not_awaited()
