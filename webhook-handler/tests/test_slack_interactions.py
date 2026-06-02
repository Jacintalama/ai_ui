"""SlackInteractionsHandler: button click -> modal, modal submit -> build."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.slack_interactions import SlackInteractionsHandler
from handlers.slack_app_builder_panel import (
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_BLOCK_ID, DESCRIPTION_INPUT_ID,
    TEMPLATE_SELECT_ACTION_ID,
)


def _handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
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
    # open_dm returns "D9" (default from _handler)
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
    # With DM flow: channel_id is the DM channel, not the origin
    assert captured["ctx"].channel_id == "D9"
    assert captured["ctx"].notify_channel is not None
    assert captured["ctx"].notify_channel_rich is not None


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
async def test_modal_submit_notify_channel_posts_to_dm():
    """With DM flow: notify_channel posts to the DM channel (not the origin)."""
    captured = {}

    async def fake_run(ctx, template_key, description):
        captured["ctx"] = ctx

    router = MagicMock()
    router.run_panel_build = fake_run
    handler, slack = _handler(router)
    # open_dm returns "D9" (default from _handler)
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
    slack.post_message.reset_mock()
    await captured["ctx"].notify_channel("`slug` is ready: http://x")
    slack.post_message.assert_awaited_with(channel="D9", text="`slug` is ready: http://x")


@pytest.mark.asyncio
async def test_unknown_interaction_type_is_noop():
    handler, slack = _handler(MagicMock())
    resp = await handler.handle_interaction({"type": "shortcut"})
    assert resp == {}


# ---------------------------------------------------------------------------
# C8 — dropdown select opens the build modal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_template_select_opens_modal():
    """A static_select action (TEMPLATE_SELECT_ACTION_ID) opens the build modal
    for the chosen template key, just like the Blank button path."""
    handler, slack = _handler(MagicMock())
    payload = {
        "type": "block_actions",
        "user": {"id": "U2", "username": "leo"},
        "trigger_id": "trig-select",
        "channel": {"id": "C-panel"},
        "actions": [{
            "action_id": TEMPLATE_SELECT_ACTION_ID,
            "type": "static_select",
            "selected_option": {"value": f"{TEMPLATE_PREFIX}portfolio"},
        }],
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-select"
    assert view["callback_id"] == f"{BUILD_PREFIX}portfolio"
    assert view["private_metadata"] == "C-panel"


# ---------------------------------------------------------------------------
# C9 — build runs in a private DM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_submit_opens_dm_and_runs_in_dm():
    """Modal submit: open_dm succeeds -> ephemeral in origin channel, post_message
    in DM, run_panel_build called with ctx.channel_id == DM id, and both
    notify_channel and notify_channel_rich are set. Calling notify_channel_rich
    posts to the DM with attachments."""
    captured = {}

    router = MagicMock()
    router.run_panel_build = AsyncMock(side_effect=lambda ctx, key, desc: captured.update(ctx=ctx))

    handler, slack = _handler(router)
    slack.open_dm = AsyncMock(return_value="D9")

    payload = {
        "type": "view_submission",
        "user": {"id": "U3", "username": "maya"},
        "team": {"id": "T1"},
        "view": {
            "callback_id": f"{BUILD_PREFIX}portfolio",
            "private_metadata": "C-panel",
            "state": {"values": {
                DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": "a portfolio for maya"}}
            }},
        },
    }

    resp = await handler.handle_interaction(payload)
    assert resp == {}  # immediate empty 200

    # Let the background task run
    await asyncio.sleep(0)

    slack.open_dm.assert_awaited_once_with("U3")
    # ephemeral in origin channel telling user to check DMs
    slack.post_ephemeral.assert_awaited_once()
    ephemeral_args = slack.post_ephemeral.call_args
    assert ephemeral_args.args[0] == "C-panel"   # channel
    assert ephemeral_args.args[1] == "U3"         # user

    # run_panel_build was called
    router.run_panel_build.assert_awaited_once()
    ctx = captured["ctx"]
    assert ctx.channel_id == "D9"
    assert ctx.user_id == "U3"
    assert ctx.notify_channel is not None
    assert ctx.notify_channel_rich is not None

    # Calling notify_channel_rich should post to the DM with attachments
    slack.post_message.reset_mock()
    await ctx.notify_channel_rich("ready", "todo-1", "https://x/p", "maya@x.com")
    slack.post_message.assert_awaited_once()
    call_kwargs = slack.post_message.call_args
    assert call_kwargs.kwargs.get("channel") == "D9" or call_kwargs.args[0] == "D9"
    # attachments must be present
    attachments = call_kwargs.kwargs.get("attachments")
    assert attachments is not None and len(attachments) > 0


@pytest.mark.asyncio
async def test_build_submit_dm_open_fails_falls_back_to_ephemeral():
    """When open_dm returns None, run_panel_build is still called with
    ctx.channel_id == origin channel; calling notify_channel_rich posts via
    post_ephemeral (not post_message)."""
    captured = {}

    router = MagicMock()
    router.run_panel_build = AsyncMock(side_effect=lambda ctx, key, desc: captured.update(ctx=ctx))

    handler, slack = _handler(router)
    slack.open_dm = AsyncMock(return_value=None)

    payload = {
        "type": "view_submission",
        "user": {"id": "U4", "username": "leo"},
        "team": {"id": "T1"},
        "view": {
            "callback_id": f"{BUILD_PREFIX}portfolio",
            "private_metadata": "C-panel",
            "state": {"values": {
                DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": "a landing page"}}
            }},
        },
    }

    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router.run_panel_build.assert_awaited_once()
    ctx = captured["ctx"]
    assert ctx.channel_id == "C-panel"  # falls back to origin

    # notify_channel_rich should use post_ephemeral (not post_message) when no DM
    slack.post_ephemeral.reset_mock()
    slack.post_message.reset_mock()
    await ctx.notify_channel_rich("ready", "todo-2", "https://x/q", "leo@x.com")
    slack.post_ephemeral.assert_awaited_once()
    slack.post_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# D10 — Publish / Unpublish buttons
# ---------------------------------------------------------------------------

from handlers.slack_app_builder_panel import (
    PUBLISH_PREFIX, UNPUBLISH_PREFIX, STATUS_PREFIX,
    ENHANCE_PREFIX, ENHANCE_MODAL_PREFIX,
)


def _mgmt_router():
    """Router mock wired for management action tests."""
    router = MagicMock()
    router._background_tasks = set()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._not_linked_text = MagicMock(return_value="not-linked msg")
    router._tasks_client = MagicMock()
    router._tasks_client.publish_app = AsyncMock(return_value={"public_url": "https://x/live"})
    router._tasks_client.unpublish_app = AsyncMock(return_value=True)
    router._tasks_client.get_project_status = AsyncMock(return_value={
        "name": "My App", "slug": "my-app", "published": True,
        "public_url": "https://x/live", "last_commit_at": "2026-01-01",
    })
    router.run_panel_enhance = AsyncMock()
    return router


def _block_actions_payload(action_id: str, user_id: str = "U1") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-mgmt",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": "C-panel"},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
    }


@pytest.mark.asyncio
async def test_publish_button_calls_publish_app_and_dms_user():
    router = _mgmt_router()
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{PUBLISH_PREFIX}my-app")
    resp = await handler.handle_interaction(payload)
    assert resp == {}

    # Let background task run
    await asyncio.sleep(0)

    router._tasks_client.publish_app.assert_awaited_once_with("u@x.com", "my-app")
    slack.open_dm.assert_awaited()
    # post_message should have been called (published attachment)
    slack.post_message.assert_awaited()
    # The message should include "my-app"
    call_kwargs = slack.post_message.call_args
    assert "my-app" in str(call_kwargs)


@pytest.mark.asyncio
async def test_publish_button_email_none_posts_not_linked():
    router = _mgmt_router()
    router._resolve_email_for_ctx = AsyncMock(return_value=None)
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{PUBLISH_PREFIX}my-app", user_id="U99")
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.publish_app.assert_not_awaited()
    # Should have posted not-linked text via DM or post_message
    slack.open_dm.assert_awaited()
    slack.post_message.assert_awaited()


@pytest.mark.asyncio
async def test_unpublish_button_email_none_posts_not_linked():
    router = _mgmt_router()
    router._resolve_email_for_ctx = AsyncMock(return_value=None)
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{UNPUBLISH_PREFIX}my-app", user_id="U99")
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.unpublish_app.assert_not_awaited()
    slack.open_dm.assert_awaited()
    slack.post_message.assert_awaited()


@pytest.mark.asyncio
async def test_unpublish_button_calls_unpublish_app_and_dms_user():
    router = _mgmt_router()
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{UNPUBLISH_PREFIX}my-app")
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.unpublish_app.assert_awaited_once_with("u@x.com", "my-app")
    slack.open_dm.assert_awaited()
    slack.post_message.assert_awaited()


# ---------------------------------------------------------------------------
# D11 — Status button
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_button_calls_get_project_status_and_dms_user():
    router = _mgmt_router()
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{STATUS_PREFIX}my-app")
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.get_project_status.assert_awaited_once_with("u@x.com", "my-app")
    slack.open_dm.assert_awaited()
    slack.post_message.assert_awaited()
    # The DM text should mention the slug and published state
    call_kwargs = slack.post_message.call_args
    text = call_kwargs.kwargs.get("text", "") or str(call_kwargs)
    assert "my-app" in text
    assert "yes" in text.lower() or "published" in text.lower()


@pytest.mark.asyncio
async def test_status_button_email_none_posts_not_linked():
    router = _mgmt_router()
    router._resolve_email_for_ctx = AsyncMock(return_value=None)
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{STATUS_PREFIX}my-app", user_id="U99")
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.get_project_status.assert_not_awaited()
    slack.open_dm.assert_awaited()
    slack.post_message.assert_awaited()


# ---------------------------------------------------------------------------
# D12 — Enhance button opens modal + enhance modal submit runs enhance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enhance_button_opens_modal():
    router = _mgmt_router()
    handler, slack = _handler(router)

    payload = _block_actions_payload(f"{ENHANCE_PREFIX}my-app")
    resp = await handler.handle_interaction(payload)
    assert resp == {}

    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-mgmt"
    assert view["callback_id"] == f"{ENHANCE_MODAL_PREFIX}my-app"


@pytest.mark.asyncio
async def test_enhance_modal_submit_runs_panel_enhance():
    router = _mgmt_router()
    handler, slack = _handler(router)
    # open_dm returns "D9" (set in _handler)

    payload = {
        "type": "view_submission",
        "trigger_id": "trig-enh",
        "user": {"id": "U1", "username": "tester"},
        "team": {"id": "T1"},
        "view": {
            "callback_id": f"{ENHANCE_MODAL_PREFIX}my-app",
            "private_metadata": "my-app",
            "state": {"values": {
                "enhance_block": {
                    "enhance_input": {"value": "make it blue"},
                }
            }},
        },
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    router.run_panel_enhance.assert_awaited_once()
    call_args = router.run_panel_enhance.call_args
    ctx_arg = call_args.args[0]
    slug_arg = call_args.args[1]
    prompt_arg = call_args.args[2]
    assert slug_arg == "my-app"
    assert prompt_arg == "make it blue"
    assert ctx_arg.channel_id == "D9"
    assert ctx_arg.notify_channel is not None
    assert ctx_arg.notify_channel_rich is not None


@pytest.mark.asyncio
async def test_enhance_modal_submit_dm_open_fails_is_silent_safe():
    """When open_dm returns None in the enhance flow, _start_enhance bails
    before building the context, so run_panel_enhance is never called and
    no exception propagates to the caller."""
    router = _mgmt_router()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")

    handler, slack = _handler(router)
    slack.open_dm = AsyncMock(return_value=None)

    payload = {
        "type": "view_submission",
        "trigger_id": "trig-enh-fail",
        "user": {"id": "U1", "username": "tester"},
        "team": {"id": "T1"},
        "view": {
            "callback_id": f"{ENHANCE_MODAL_PREFIX}my-app",
            "private_metadata": "my-app",
            "state": {"values": {
                "enhance_block": {
                    "enhance_input": {"value": "make it blue"},
                }
            }},
        },
    }
    resp = await handler.handle_interaction(payload)
    assert resp == {}  # immediate empty 200, no exception
    await asyncio.sleep(0)

    # Bailed before building ctx: enhance must NOT have been called
    router.run_panel_enhance.assert_not_awaited()
