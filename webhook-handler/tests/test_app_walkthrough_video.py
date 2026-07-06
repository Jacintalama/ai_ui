"""Tests for the Discord App Builder 'Walkthrough video' button (Task 11).

Hermetic: no real network, no real sleeping — the tasks client is a mock and
the watcher is stubbed out on the router instance under test.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.app_builder_panel import WALKVIDEO_PREFIX, build_project_menu_components
from handlers.commands import CommandRouter, CommandContext


def _ctx(*, respond_components=None, notify_channel=None, notify_channel_msg=None,
         platform="discord"):
    return CommandContext(
        user_id="100", user_name="alice", channel_id="c", raw_text="",
        subcommand="", arguments="", platform=platform, respond=AsyncMock(),
        respond_components=respond_components, notify_channel=notify_channel,
        notify_channel_msg=notify_channel_msg,
    )


def _router(tasks_client, *, email="u@x.com"):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = tasks_client
    r._discord = None
    r._background_tasks = set()
    r._resolve_email_for_ctx = AsyncMock(return_value=email)
    r._respond_not_linked = AsyncMock()
    return r


def test_project_menu_has_walkthrough_video_button():
    rows = build_project_menu_components("myapp", published=False,
                                         preview_url="https://x/p/", owner="o@x.com")
    ids = [c.get("custom_id") for row in rows for c in row.get("components", [])]
    assert f"{WALKVIDEO_PREFIX}myapp" in ids


@pytest.mark.asyncio
async def test_run_app_walkthrough_video_drives_pipeline_with_empty_prompt():
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "name": "My App", "published": False, "public_url": ""})
    tc.create_video_draft = AsyncMock(return_value={"id": "vj1"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    tc.queue_video = AsyncMock(return_value={"status": "queued", "queue_position": 0})
    r = _router(tc)
    r._watch_video = AsyncMock()
    nc = AsyncMock()
    ctx = _ctx(notify_channel=nc)
    await r.run_app_walkthrough_video(ctx, "myapp")
    draft_call = tc.create_video_draft.await_args
    assert draft_call.args[2] == ""                      # empty prompt -> walk default
    assert draft_call.kwargs["render_mode"] == "remotion"
    cap_call = tc.capture_video_screenshots.await_args
    assert "/tasks/preview-app/myapp/" in cap_call.args[2]
    tc.queue_video.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_app_walkthrough_video_prefers_public_url():
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "name": "My App", "published": True, "public_url": "https://live.app/"})
    tc.create_video_draft = AsyncMock(return_value={"id": "vj1"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    tc.queue_video = AsyncMock(return_value={"status": "queued"})
    r = _router(tc)
    r._watch_video = AsyncMock()
    await r.run_app_walkthrough_video(_ctx(notify_channel=AsyncMock()), "myapp")
    assert tc.capture_video_screenshots.await_args.args[2] == "https://live.app/"


@pytest.mark.asyncio
async def test_run_app_walkthrough_video_status_error_is_clean():
    from clients.tasks import TasksAPIError
    tc = MagicMock()
    tc.get_project_status = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    tc.create_video_draft = AsyncMock()
    r = _router(tc)
    ctx = _ctx()
    await r.run_app_walkthrough_video(ctx, "myapp")
    tc.create_video_draft.assert_not_awaited()
    ctx.respond.assert_awaited()
