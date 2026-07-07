"""Tests for the Slack App Builder 'Walkthrough video' button (Task 12).

Mirrors test_slack_video_interactions.py's `_handler`/router fixtures. Hermetic:
no real Slack or tasks calls, everything is a mock.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.app_builder_panel import WALKVIDEO_PREFIX
from handlers.slack_app_builder_panel import build_apps_list_blocks
from handlers.slack_interactions import SlackInteractionsHandler


def _action_ids(blocks):
    return [e.get("action_id") for b in blocks if b.get("type") == "actions"
            for e in b.get("elements", [])]


def test_apps_list_rows_have_walkthrough_button():
    blocks = build_apps_list_blocks(
        [{"slug": "myapp", "name": "My App", "published": False}], owner="o@x.com")
    assert f"{WALKVIDEO_PREFIX}myapp" in _action_ids(blocks)


def test_walkthrough_button_present_for_published_apps_too():
    blocks = build_apps_list_blocks(
        [{"slug": "myapp", "name": "My App", "published": True,
          "public_url": "https://live.app/"}], owner="o@x.com")
    assert f"{WALKVIDEO_PREFIX}myapp" in _action_ids(blocks)


def _handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _router():
    """Router mock wired for the walkthrough-video interaction tests."""
    router = MagicMock()
    router._background_tasks = set()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._not_linked_text = MagicMock(return_value="not-linked msg")
    tc = MagicMock()
    tc.get_project_status = AsyncMock(
        return_value={"name": "My App", "published": False,
                      "public_url": "", "slug": "myapp"})
    tc.create_video_draft = AsyncMock(return_value={"id": "vj1"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    tc.queue_video = AsyncMock(return_value={"status": "queued"})
    router._tasks_client = tc
    return router


def _block_actions_payload(action_id: str, user_id: str = "U1",
                           channel: str = "C-apps") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-1",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": channel},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
    }


async def _run_spawned(router, payload):
    """Dispatch a block_actions payload and drive any spawned background task
    to completion (mirrors test_vid_apply_spawns_apply_and_delivers)."""
    import asyncio
    handler, slack = _handler(router)
    handler._watch_slack_video = AsyncMock()
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    pending = list(router._background_tasks)
    if pending:
        await asyncio.gather(*pending)
    return handler, slack


@pytest.mark.asyncio
async def test_walkthrough_video_button_drives_full_pipeline():
    """Test C: clicking the button drives get_project_status, create_video_draft
    (empty prompt, remotion mode), capture_video_screenshots (preview url),
    queue_video, then hands off to the Slack video watcher."""
    router = _router()
    handler, slack = await _run_spawned(
        router, _block_actions_payload(f"{WALKVIDEO_PREFIX}myapp"))

    router._tasks_client.get_project_status.assert_awaited_once_with("u@x.com", "myapp")
    draft_call = router._tasks_client.create_video_draft.await_args
    assert draft_call.args[2] == ""
    assert draft_call.kwargs["render_mode"] == "remotion"
    cap_call = router._tasks_client.capture_video_screenshots.await_args
    assert "/tasks/preview-app/myapp/" in cap_call.args[2]
    router._tasks_client.queue_video.assert_awaited_once_with("u@x.com", "vj1")
    handler._watch_slack_video.assert_awaited_once()
    watch_args = handler._watch_slack_video.await_args.args
    assert watch_args[0] == "u@x.com"
    assert watch_args[1] == "vj1"
    assert watch_args[2] == "U1"


@pytest.mark.asyncio
async def test_walkthrough_video_status_error_posts_clean_error_and_skips_draft():
    """Test D: get_project_status raising means create_video_draft must never
    be called, and the user gets a clean error DM instead of a traceback."""
    router = _router()
    router._tasks_client.get_project_status = AsyncMock(
        side_effect=RuntimeError("boom"))

    handler, slack = await _run_spawned(
        router, _block_actions_payload(f"{WALKVIDEO_PREFIX}myapp"))

    router._tasks_client.create_video_draft.assert_not_awaited()
    slack.open_dm.assert_awaited()
    dm_texts = " ".join(
        c.kwargs.get("text", "") or ""
        for c in slack.post_message.call_args_list
        if c.kwargs.get("channel") == "D9"
    )
    assert "Traceback" not in dm_texts
    assert dm_texts.strip() != ""
