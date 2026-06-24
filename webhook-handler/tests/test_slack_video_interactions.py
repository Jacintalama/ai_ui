"""SlackInteractionsHandler: video panel button clicks + modal submits + runner.

Mirrors the schedule interaction tests (test_slack_schedule_interactions.py):
Mock slack + router._tasks_client, AsyncMocks, router._background_tasks = set().
No real Slack or tasks calls.
"""
import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.slack_interactions import SlackInteractionsHandler
from handlers import slack_video_panel as svp


def _handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _video_router():
    """Router mock wired for video interaction tests."""
    router = MagicMock()
    router._background_tasks = set()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._not_linked_text = MagicMock(return_value="not-linked msg")
    tc = MagicMock()
    tc.create_video_draft = AsyncMock(return_value={"id": "j1"})
    tc.set_video_draft_fields = AsyncMock(return_value={})
    tc.capture_video_screenshots = AsyncMock(return_value={})
    tc.queue_video = AsyncMock(return_value={})
    tc.get_video = AsyncMock(
        return_value={"status": "done", "share_url": "http://x/v", "title": "T"})
    tc.list_videos = AsyncMock(return_value={"videos": []})
    tc.refine_video = AsyncMock(return_value={"can_apply": True})
    tc.apply_video = AsyncMock(return_value={})
    router._tasks_client = tc
    return router


def _block_actions_payload(action_id: str, user_id: str = "U1",
                           channel: str = "C-vid") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-vid",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": channel},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
    }


def _create_view_submission(url: str, *, channel: str = "C-vid",
                            user_id: str = "U1") -> dict:
    return {
        "type": "view_submission",
        "user": {"id": user_id, "username": "tester"},
        "view": {
            "callback_id": svp.CREATE_CALLBACK,
            "private_metadata": channel,
            "state": {"values": {
                "url": {"url": {"value": url}},
                "prompt": {"prompt": {"value": "show the homepage"}},
                "title": {"title": {"value": "My demo"}},
            }},
        },
    }


def _refine_view_submission(meta: str, change: str, user_id: str = "U1") -> dict:
    return {
        "type": "view_submission",
        "user": {"id": user_id, "username": "tester"},
        "view": {
            "callback_id": svp.REFINE_CALLBACK,
            "private_metadata": meta,
            "state": {"values": {
                "change": {"change": {"value": change}},
            }},
        },
    }


# ---------------------------------------------------------------------------
# block_actions: New / Refine open modals immediately (trigger-TTL safe)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vid_new_opens_modal_without_any_tasks_call():
    """New-video click must open the modal with NO awaited tasks-client call
    before it (trigger_id ~3s TTL)."""
    router = _video_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(_block_actions_payload(svp.NEW_ID))
    assert resp == {}

    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-vid"
    assert view["callback_id"] == svp.CREATE_CALLBACK
    assert view["private_metadata"] == "C-vid"
    # No tasks-client method was touched at all before/at open time.
    assert router._tasks_client.mock_calls == []


@pytest.mark.asyncio
async def test_vid_refine_opens_refine_modal():
    router = _video_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _block_actions_payload(f"{svp.REFINE_PREFIX}j7"))
    assert resp == {}

    slack.open_modal.assert_awaited_once()
    _trigger, view = slack.open_modal.call_args.args
    assert view["callback_id"] == svp.REFINE_CALLBACK
    # job_id is preserved; channel is stashed alongside it.
    assert view["private_metadata"].split("|")[0] == "j7"
    assert "C-vid" in view["private_metadata"]


@pytest.mark.asyncio
async def test_vid_list_spawns_and_posts_list():
    router = _video_router()
    router._tasks_client.list_videos = AsyncMock(
        return_value={"videos": [{"id": "j1", "title": "Demo", "status": "done"}]})
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(_block_actions_payload(svp.LIST_ID))
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.list_videos.assert_awaited_once_with("u@x.com")
    slack.post_message.assert_awaited()
    args, kwargs = slack.post_message.call_args
    assert kwargs.get("blocks")


# ---------------------------------------------------------------------------
# view_submission: create modal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_callback_valid_spawns_runner():
    router = _video_router()
    handler, slack = _handler(router)
    handler._run_slack_video = AsyncMock()

    resp = await handler.handle_interaction(
        _create_view_submission("https://example.com"))
    assert resp == {}
    await asyncio.sleep(0)

    handler._run_slack_video.assert_awaited_once()
    args = handler._run_slack_video.call_args.args
    assert args[0] == "U1"
    fields = args[1]
    assert fields["url"] == "https://example.com"
    assert fields["channel_id"] == "C-vid"


@pytest.mark.asyncio
async def test_create_callback_blank_url_returns_errors():
    router = _video_router()
    handler, _slack = _handler(router)
    handler._run_slack_video = AsyncMock()

    resp = await handler.handle_interaction(_create_view_submission("   "))
    assert resp["response_action"] == "errors"
    assert "url" in resp["errors"]
    handler._run_slack_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_callback_non_http_url_returns_errors():
    router = _video_router()
    handler, _slack = _handler(router)
    handler._run_slack_video = AsyncMock()

    resp = await handler.handle_interaction(
        _create_view_submission("ftp://nope.example"))
    assert resp["response_action"] == "errors"
    assert "url" in resp["errors"]
    handler._run_slack_video.assert_not_awaited()


# ---------------------------------------------------------------------------
# _run_slack_video runner
# ---------------------------------------------------------------------------

def _fields(url="https://example.com", channel="C-vid"):
    return {
        "url": url,
        "prompt": "show the homepage",
        "title": "My demo",
        "style": svp.DEFAULT_STYLE,
        "voice": svp.DEFAULT_VOICE,
        "mode": svp.DEFAULT_MODE,
        "channel_id": channel,
    }


@pytest.mark.asyncio
async def test_run_slack_video_happy_path_posts_result_blocks():
    router = _video_router()
    handler, slack = _handler(router)

    with patch("handlers.slack_interactions.asyncio.sleep", new=AsyncMock()):
        await handler._run_slack_video("U1", _fields())

    router._tasks_client.create_video_draft.assert_awaited_once()
    router._tasks_client.capture_video_screenshots.assert_awaited_once()
    router._tasks_client.queue_video.assert_awaited_once()

    # A posted message carries the result blocks with the share_url link.
    found = False
    for call in slack.post_message.call_args_list:
        blocks = call.kwargs.get("blocks")
        if blocks and "http://x/v" in json.dumps(blocks):
            found = True
    assert found, "expected a result message containing the share_url"


@pytest.mark.asyncio
async def test_run_slack_video_failed_path_posts_clean_error():
    router = _video_router()
    router._tasks_client.get_video = AsyncMock(
        return_value={"status": "failed", "error": "boom"})
    handler, slack = _handler(router)

    with patch("handlers.slack_interactions.asyncio.sleep", new=AsyncMock()):
        await handler._run_slack_video("U1", _fields())

    slack.post_message.assert_awaited()
    blob = json.dumps([c.args for c in slack.post_message.call_args_list]) \
        + json.dumps([c.kwargs for c in slack.post_message.call_args_list])
    assert "Traceback" not in blob
    assert "boom" in blob


@pytest.mark.asyncio
async def test_run_slack_video_exception_posts_clean_error():
    router = _video_router()
    router._tasks_client.create_video_draft = AsyncMock(
        side_effect=RuntimeError("kaboom"))
    handler, slack = _handler(router)

    with patch("handlers.slack_interactions.asyncio.sleep", new=AsyncMock()):
        await handler._run_slack_video("U1", _fields())

    slack.post_message.assert_awaited()
    blob = json.dumps([c.args for c in slack.post_message.call_args_list])
    assert "Traceback" not in blob
    assert "Couldn't make the video" in blob


# ---------------------------------------------------------------------------
# view_submission: refine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refine_callback_posts_proposal_when_can_apply():
    router = _video_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _refine_view_submission("j7|C-vid", "make it shorter"))
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.refine_video.assert_awaited_once_with(
        "u@x.com", "j7", "make it shorter")
    slack.post_message.assert_awaited()
    args, kwargs = slack.post_message.call_args
    assert kwargs.get("blocks")
    assert "C-vid" in (args[0] if args else kwargs.get("channel", ""))


# ---------------------------------------------------------------------------
# block_actions: apply
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vid_apply_spawns_apply_and_delivers():
    router = _video_router()
    handler, slack = _handler(router)

    with patch("handlers.slack_interactions.asyncio.sleep", new=AsyncMock()):
        resp = await handler.handle_interaction(
            _block_actions_payload(f"{svp.APPLY_PREFIX}j9"))
        assert resp == {}
        # drive the spawned task to completion (asyncio.sleep is patched, so a
        # bare sleep(0) yield won't schedule it — gather the task instead).
        pending = list(router._background_tasks)
        if pending:
            await asyncio.gather(*pending)

    router._tasks_client.apply_video.assert_awaited_once_with("u@x.com", "j9")
