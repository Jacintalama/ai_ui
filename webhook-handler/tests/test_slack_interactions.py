"""SlackInteractionsHandler: button click -> modal, modal submit -> build."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.slack_interactions import SlackInteractionsHandler
from handlers.slack_app_builder_panel import (
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_BLOCK_ID, DESCRIPTION_INPUT_ID,
)


def _handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


@pytest.mark.asyncio
async def test_button_click_opens_modal():
    handler, slack = _handler(MagicMock())
    payload = {
        "type": "block_actions",
        "user": {"id": "U1", "username": "maya"},
        "trigger_id": "trig-1",
        "channel": {"id": "C1"},
        "actions": [{"action_id": f"{TEMPLATE_PREFIX}portfolio", "type": "button"}],
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}  # empty 200 ack
    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-1"
    assert view["callback_id"] == f"{BUILD_PREFIX}portfolio"
    assert view["private_metadata"] == "C1"  # channel travels via the modal


@pytest.mark.asyncio
async def test_unknown_button_is_noop():
    handler, slack = _handler(MagicMock())
    payload = {
        "type": "block_actions",
        "trigger_id": "t",
        "actions": [{"action_id": "something:else"}],
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    slack.open_modal.assert_not_awaited()


@pytest.mark.asyncio
async def test_modal_submit_routes_build():
    captured = {}

    async def fake_run(ctx, template_key, description):
        captured.update(ctx=ctx, key=template_key, desc=description)

    router = MagicMock()
    router.run_panel_build = fake_run
    handler, slack = _handler(router)
    payload = {
        "type": "view_submission",
        "user": {"id": "U1", "username": "maya"},
        "view": {
            "callback_id": f"{BUILD_PREFIX}portfolio",
            "private_metadata": "C-chan",
            "state": {"values": {
                DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": "a portfolio for Maya"}}
            }},
        },
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}  # empty 200 closes the modal
    await asyncio.sleep(0)
    assert captured["key"] == "portfolio"
    assert captured["desc"] == "a portfolio for Maya"
    assert captured["ctx"].user_id == "U1"
    assert captured["ctx"].platform == "slack"
    assert captured["ctx"].channel_id == "C-chan"
    assert captured["ctx"].notify_channel is not None


@pytest.mark.asyncio
async def test_modal_submit_blank_key():
    captured = {}

    async def fake_run(ctx, template_key, description):
        captured["key"] = template_key

    router = MagicMock()
    router.run_panel_build = fake_run
    handler, slack = _handler(router)
    payload = {
        "type": "view_submission",
        "user": {"id": "U1", "name": "x"},
        "view": {
            "callback_id": BUILD_PREFIX,
            "private_metadata": "C1",
            "state": {"values": {
                DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": "a blank app"}}
            }},
        },
    }
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    assert captured["key"] is None


@pytest.mark.asyncio
async def test_modal_submit_notify_channel_posts_to_channel():
    """The notify_channel wired by the handler posts to the modal's channel."""
    captured = {}

    async def fake_run(ctx, template_key, description):
        captured["ctx"] = ctx

    router = MagicMock()
    router.run_panel_build = fake_run
    handler, slack = _handler(router)
    payload = {
        "type": "view_submission",
        "user": {"id": "U1", "username": "maya"},
        "view": {
            "callback_id": f"{BUILD_PREFIX}portfolio",
            "private_metadata": "C-target",
            "state": {"values": {
                DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": "x"}}
            }},
        },
    }
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    await captured["ctx"].notify_channel("`slug` is ready: http://x")
    slack.post_message.assert_awaited_with(channel="C-target", text="`slug` is ready: http://x")


@pytest.mark.asyncio
async def test_unknown_interaction_type_is_noop():
    handler, slack = _handler(MagicMock())
    resp = await handler.handle_interaction({"type": "shortcut"})
    assert resp == {}
