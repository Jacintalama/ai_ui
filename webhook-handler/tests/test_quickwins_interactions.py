"""DiscordCommandHandler routing for linking (aiuilink:*) and schedule edit."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

import config
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import (
    LINK_START_ID, LINK_MODAL_ID, LINK_EMAIL_INPUT,
    SCHED_WHAT_INPUT, SCHED_WHEN_INPUT,
)


def _handler(router):
    d = MagicMock()
    d.edit_original = AsyncMock(return_value=True)
    d.post_channel_message = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=d, command_router=router)


def _component(custom_id, user_id="100"):
    return {"type": 3, "id": "i", "token": "t", "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "alice"}}, "channel_id": "c"}


def _modal(custom_id, fields, user_id="100"):
    rows = [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]}
            for k, v in fields.items()]
    return {"type": 5, "id": "i", "token": "t",
            "data": {"custom_id": custom_id, "components": rows},
            "member": {"user": {"id": user_id, "username": "alice"}}, "channel_id": "c"}


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


# --- Linking ---
@pytest.mark.asyncio
async def test_link_button_opens_modal():
    resp = await _handler(MagicMock()).handle_interaction(_component(LINK_START_ID))
    assert resp["type"] == 9
    assert resp["data"]["custom_id"] == LINK_MODAL_ID


@pytest.mark.asyncio
async def test_link_modal_valid_email_requests_and_posts_admin(monkeypatch):
    monkeypatch.setattr(config.settings, "discord_alert_channel_id", "admin-chan")
    router = MagicMock()
    router.request_link = AsyncMock(return_value={"status": "pending"})
    handler = _handler(router)
    resp = await handler.handle_interaction(
        _modal(LINK_MODAL_ID, {LINK_EMAIL_INPUT: "alice@x.com"}))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    router.request_link.assert_awaited_once_with("100", "alice", "alice@x.com")
    # posted an approve/reject request to the admin channel
    args, kwargs = handler.discord.post_channel_message.call_args
    assert args[0] == "admin-chan"
    comp_ids = {b["custom_id"] for row in kwargs["components"] for b in row["components"]}
    assert "aiuilink:approve:100" in comp_ids and "aiuilink:reject:100" in comp_ids


@pytest.mark.asyncio
async def test_link_modal_invalid_email_rejected(monkeypatch):
    router = MagicMock()
    router.request_link = AsyncMock()
    resp = await _handler(router).handle_interaction(
        _modal(LINK_MODAL_ID, {LINK_EMAIL_INPUT: "not-an-email"}))
    assert resp["type"] == 4 and resp["data"]["flags"] == 64
    await _drain()
    router.request_link.assert_not_called()


@pytest.mark.asyncio
async def test_link_approve_calls_router():
    router = MagicMock()
    router.approve_link = AsyncMock(return_value={"email": "alice@x.com"})
    handler = _handler(router)
    resp = await handler.handle_interaction(_component("aiuilink:approve:100"))
    assert resp["type"] in (6, 7)
    await _drain()
    router.approve_link.assert_awaited_once()
    assert router.approve_link.await_args.args[0] == "100"


@pytest.mark.asyncio
async def test_link_reject_calls_router():
    router = MagicMock()
    router.reject_link = AsyncMock(return_value=True)
    handler = _handler(router)
    await handler.handle_interaction(_component("aiuilink:reject:100"))
    await _drain()
    router.reject_link.assert_awaited_once_with("100")


# --- Edit a schedule ---
@pytest.mark.asyncio
async def test_edit_button_opens_prefilled_modal():
    router = MagicMock()
    router.get_schedule_for_edit = AsyncMock(
        return_value={"what": "summarize emails", "when": "every morning"})
    resp = await _handler(router).handle_interaction(_component("aiuisched:edit:sid1"))
    assert resp["type"] == 9
    assert resp["data"]["custom_id"] == "aiuisched:editmodal:sid1"
    inputs = {i["custom_id"]: i for row in resp["data"]["components"] for i in row["components"]}
    assert inputs[SCHED_WHAT_INPUT]["value"] == "summarize emails"
    assert inputs[SCHED_WHEN_INPUT]["value"] == "every morning"


@pytest.mark.asyncio
async def test_edit_button_missing_schedule_is_graceful():
    router = MagicMock()
    router.get_schedule_for_edit = AsyncMock(return_value=None)
    resp = await _handler(router).handle_interaction(_component("aiuisched:edit:ghost"))
    assert resp["type"] == 4 and resp["data"]["flags"] == 64


@pytest.mark.asyncio
async def test_editmodal_submit_parses_and_updates():
    captured = {}

    async def fake_edit(ctx, schedule_id, *, name, cron, prompt):
        captured.update(id=schedule_id, name=name, cron=cron, prompt=prompt)
    router = MagicMock()
    router.run_schedule_edit = fake_edit
    handler = _handler(router)
    resp = await handler.handle_interaction(_modal(
        "aiuisched:editmodal:sid1",
        {SCHED_WHAT_INPUT: "summarize emails", SCHED_WHEN_INPUT: "every monday at 9am"}))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    assert captured["id"] == "sid1"
    assert captured["cron"] == "0 9 * * 1"
    assert captured["prompt"] == "summarize emails"


@pytest.mark.asyncio
async def test_editmodal_submit_unparseable_when_errors():
    router = MagicMock()
    router.run_schedule_edit = AsyncMock()
    resp = await _handler(router).handle_interaction(_modal(
        "aiuisched:editmodal:sid1",
        {SCHED_WHAT_INPUT: "do stuff", SCHED_WHEN_INPUT: "whenever"}))
    assert resp["type"] == 4 and resp["data"]["flags"] == 64
    await _drain()
    router.run_schedule_edit.assert_not_called()
