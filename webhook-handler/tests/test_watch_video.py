"""Tests for CommandRouter._watch_video / _deliver_video (Task B4).

Hermetic: poll_seconds=0 (no real sleeping), small max_polls, no network —
the tasks client and DiscordClient are mocks.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(notify, *, notify_channel_msg=None, channel_id="c"):
    return CommandContext(
        user_id="100", user_name="alice", channel_id=channel_id, raw_text="",
        subcommand="", arguments="", platform="discord", respond=AsyncMock(),
        notify_channel=notify, notify_channel_msg=notify_channel_msg,
    )


def _router(tasks_client, *, discord=None):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = tasks_client
    r._discord = discord
    r._background_tasks = set()
    return r


@pytest.mark.asyncio
async def test_watch_video_delivers_link_on_done_no_discord():
    # statuses [rendering, done] -> _deliver_video; with _discord=None it falls
    # back to the notify_channel capability link.
    tc = MagicMock()
    tc.get_video = AsyncMock(side_effect=[
        {"status": "rendering"},
        {"status": "done"},
        {"status": "done", "title": "My vid", "share_url": "http://share/x"},
    ])
    tc.video_versions = AsyncMock(return_value={"versions": []})
    r = _router(tc, discord=None)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)),
               notify_channel_msg=AsyncMock())
    await r._watch_video(ctx, "u@x.com", "job1", poll_seconds=0, max_polls=5)
    assert posted, "expected a channel message"
    assert "ready" in posted[0].lower() and "http://share/x" in posted[0]


@pytest.mark.asyncio
async def test_watch_video_attaches_on_done_with_discord():
    # With a DiscordClient present and a small blob, the MP4 is attached and the
    # fallback link is NOT posted.
    tc = MagicMock()
    tc.get_video = AsyncMock(side_effect=[
        {"status": "done", "title": "My vid", "share_url": "http://share/x"},
        {"status": "done", "title": "My vid", "share_url": "http://share/x"},
    ])
    tc.video_versions = AsyncMock(return_value={"versions": []})
    tc.download_video_bytes = AsyncMock(return_value=b"tinymp4")
    discord = MagicMock()
    discord.post_channel_file = AsyncMock(return_value=True)
    r = _router(tc, discord=discord)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_video(ctx, "u@x.com", "job1", poll_seconds=0, max_polls=3)
    discord.post_channel_file.assert_awaited_once()
    assert posted == [], "attach succeeded -> no fallback link expected"


@pytest.mark.asyncio
async def test_watch_video_reports_failure():
    tc = MagicMock()
    tc.get_video = AsyncMock(side_effect=[
        {"status": "rendering"},
        {"status": "failed", "error": "render boom"},
    ])
    r = _router(tc, discord=None)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_video(ctx, "u@x.com", "job1", poll_seconds=0, max_polls=3)
    assert posted and "failed" in posted[0].lower()
    assert "render boom" in posted[0]


@pytest.mark.asyncio
async def test_watch_video_noop_without_notify_channel():
    tc = MagicMock()
    tc.get_video = AsyncMock(return_value={"status": "done"})
    r = _router(tc, discord=None)
    ctx = _ctx(None)
    await r._watch_video(ctx, "u@x.com", "job1", poll_seconds=0, max_polls=3)
    tc.get_video.assert_not_called()


@pytest.mark.asyncio
async def test_watch_video_gives_up_after_consecutive_errors():
    tc = MagicMock()
    tc.get_video = AsyncMock(side_effect=TasksAPIError(503, "down"))
    r = _router(tc, discord=None)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_video(ctx, "u@x.com", "job1", poll_seconds=0, max_polls=50)
    assert posted and "lost track" in posted[0].lower()
