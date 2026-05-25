"""DiscordCommandHandler routing for the Schedules UX (aiuisched:* ids)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import (
    SCHED_NEW_ID, SCHED_LIST_ID, SCHED_MODAL_ID,
    SCHED_WHAT_INPUT, SCHED_WHEN_INPUT, SCHED_CONFIRM_PREFIX,
)


def _handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    discord.create_private_thread = AsyncMock(return_value="thread-9")
    discord.add_thread_member = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=discord, command_router=router)


def _component(custom_id, user_id="100"):
    return {"type": 3, "id": "i", "token": "t", "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "alice"}}, "channel_id": "chan-1"}


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_new_button_opens_schedule_modal():
    resp = await _handler(MagicMock()).handle_interaction(_component(SCHED_NEW_ID))
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == SCHED_MODAL_ID


@pytest.mark.asyncio
async def test_modal_submit_parseable_shows_confirm_card():
    handler = _handler(MagicMock())
    submit = {"type": 5, "id": "i", "token": "tok1", "channel_id": "chan-1",
              "member": {"user": {"id": "100", "username": "alice"}},
              "data": {"custom_id": SCHED_MODAL_ID, "components": [
                  {"type": 1, "components": [{"type": 4, "custom_id": SCHED_WHAT_INPUT, "value": "summarize emails"}]},
                  {"type": 1, "components": [{"type": 4, "custom_id": SCHED_WHEN_INPUT, "value": "every morning"}]},
              ]}}
    resp = await handler.handle_interaction(submit)
    assert resp["type"] == 4  # CHANNEL_MESSAGE_WITH_SOURCE
    assert resp["data"]["flags"] == 64  # ephemeral
    buttons = [b for row in resp["data"]["components"] for b in row["components"]]
    assert any(b["custom_id"].startswith(SCHED_CONFIRM_PREFIX) for b in buttons)
    assert "8:00 AM" in resp["data"]["content"]


@pytest.mark.asyncio
async def test_modal_submit_unparseable_when_errors_no_card():
    handler = _handler(MagicMock())
    submit = {"type": 5, "id": "i", "token": "t", "channel_id": "c",
              "member": {"user": {"id": "100", "username": "a"}},
              "data": {"custom_id": SCHED_MODAL_ID, "components": [
                  {"type": 1, "components": [{"type": 4, "custom_id": SCHED_WHAT_INPUT, "value": "do stuff"}]},
                  {"type": 1, "components": [{"type": 4, "custom_id": SCHED_WHEN_INPUT, "value": "whenever maybe"}]},
              ]}}
    resp = await handler.handle_interaction(submit)
    assert resp["type"] == 4 and resp["data"]["flags"] == 64
    assert not resp["data"].get("components")


@pytest.mark.asyncio
async def test_confirm_creates_schedule_with_thread_delivery():
    captured = {}

    async def fake_create(ctx, *, name, cron, prompt, delivery_channel_id=None):
        captured.update(name=name, cron=cron, prompt=prompt,
                        delivery=delivery_channel_id, user=ctx.user_id)
    router = MagicMock()
    router.run_schedule_create = fake_create
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock(return_value=True)
    handler = _handler(router)

    submit = {"type": 5, "id": "i", "token": "tok1", "channel_id": "chan-1",
              "member": {"user": {"id": "100", "username": "alice"}},
              "data": {"custom_id": SCHED_MODAL_ID, "components": [
                  {"type": 1, "components": [{"type": 4, "custom_id": SCHED_WHAT_INPUT, "value": "summarize emails"}]},
                  {"type": 1, "components": [{"type": 4, "custom_id": SCHED_WHEN_INPUT, "value": "every morning"}]},
              ]}}
    card = await handler.handle_interaction(submit)
    confirm_id = next(
        b["custom_id"] for row in card["data"]["components"]
        for b in row["components"] if b["custom_id"].startswith(SCHED_CONFIRM_PREFIX)
    )
    resp = await handler.handle_interaction(_component(confirm_id))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64  # ephemeral deferred
    await _drain()
    handler.discord.create_private_thread.assert_awaited()
    assert captured["cron"] == "0 8 * * *"
    assert captured["prompt"] == "summarize emails"
    assert captured["delivery"] == "thread-9"
    assert captured["user"] == "100"


@pytest.mark.asyncio
async def test_confirm_unknown_token_is_graceful():
    router = MagicMock()
    router.run_schedule_create = AsyncMock()
    handler = _handler(router)
    resp = await handler.handle_interaction(_component("aiuisched:confirm:ghosttoken"))
    assert resp["type"] == 5  # ack, no crash
    await _drain()
    router.run_schedule_create.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_updates_message():
    resp = await _handler(MagicMock()).handle_interaction(_component("aiuisched:cancel:tok"))
    assert resp["type"] == 7  # UPDATE_MESSAGE
    assert "cancel" in resp["data"]["content"].lower()


@pytest.mark.asyncio
async def test_list_button_acks_and_routes():
    calls = []

    async def fake_list(ctx):
        calls.append(ctx.user_id)
    router = MagicMock()
    router.run_schedule_list = fake_list
    handler = _handler(router)
    resp = await handler.handle_interaction(_component(SCHED_LIST_ID))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    assert calls == ["100"]


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,action", [
    ("aiuisched:run:", "run"), ("aiuisched:pause:", "pause"),
    ("aiuisched:resume:", "resume"), ("aiuisched:del:", "del"),
])
async def test_action_button_acks_and_routes(prefix, action):
    calls = []

    async def fake_action(ctx, act, sid):
        calls.append((act, sid, ctx.user_id))
    router = MagicMock()
    router.run_schedule_action = fake_action
    handler = _handler(router)
    resp = await handler.handle_interaction(_component(f"{prefix}sid-7"))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    assert calls == [(action, "sid-7", "100")]
