"""Tests for CommandRouter video runner methods (Task B4).

Hermetic: no real sleeping (no watcher is spawned — notify_channel is None),
no network — the tasks client is a mock.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


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


# --- run_video_add ---------------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_add_pushes_urls_and_replies_components():
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job1"})
    tc.add_video_screenshots_urls = AsyncMock(return_value={"count": 3})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    urls = ["http://cdn/1.png", "http://cdn/2.png"]
    await r.run_video_add(ctx, urls)
    tc.add_video_screenshots_urls.assert_awaited_once_with("u@x.com", "job1", urls)
    rc.assert_awaited_once()
    msg, components = rc.await_args.args
    assert "3/12" in msg
    assert isinstance(components, list) and components  # a Generate button row


@pytest.mark.asyncio
async def test_run_video_add_plain_reply_without_components():
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job1"})
    tc.add_video_screenshots_urls = AsyncMock(return_value={"count": 1})
    r = _router(tc)
    ctx = _ctx(respond_components=None)
    await r.run_video_add(ctx, ["http://cdn/1.png"])
    ctx.respond.assert_awaited()


@pytest.mark.asyncio
async def test_run_video_add_no_draft_prompts_new_video():
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value=None)
    r = _router(tc)
    ctx = _ctx(respond_components=AsyncMock())
    await r.run_video_add(ctx, ["http://cdn/1.png"])
    ctx.respond.assert_awaited()
    assert "New video" in ctx.respond.await_args.args[0]
    tc.add_video_screenshots_urls.assert_not_called()


@pytest.mark.asyncio
async def test_run_video_add_no_urls():
    tc = MagicMock()
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_add(ctx, [])
    ctx.respond.assert_awaited()
    tc.get_current_video_draft.assert_not_called()


@pytest.mark.asyncio
async def test_run_video_set_details_patches_and_confirms():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock(return_value={"status": "ok"})
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_set_details(ctx, "job1", title="T", prompt="P")
    tc.set_video_draft_fields.assert_awaited_once_with("u@x.com", "job1", title="T", prompt="P")
    ctx.respond.assert_awaited()


@pytest.mark.asyncio
async def test_run_video_set_details_unlinked():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    ctx = _ctx()
    await r.run_video_set_details(ctx, "job1", title="T", prompt="P")
    r._respond_not_linked.assert_awaited()


@pytest.mark.asyncio
async def test_run_video_add_unlinked():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    ctx = _ctx()
    await r.run_video_add(ctx, ["http://cdn/1.png"])
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_video_add_api_error():
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job1"})
    tc.add_video_screenshots_urls = AsyncMock(side_effect=TasksAPIError(400, "too many"))
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_add(ctx, ["http://cdn/1.png"])
    ctx.respond.assert_awaited()
    assert "too many" in ctx.respond.await_args.args[0]


# --- run_video_generate ----------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_generate_queues_and_acks_no_watcher():
    # notify_channel=None -> no background watcher is spawned (keeps test hermetic).
    tc = MagicMock()
    tc.queue_video = AsyncMock(return_value={"queue_position": 0})
    r = _router(tc)
    ctx = _ctx(notify_channel=None)
    await r.run_video_generate(ctx, "job1")
    tc.queue_video.assert_awaited_once_with("u@x.com", "job1")
    ctx.respond.assert_awaited()
    assert "Rendering" in ctx.respond.await_args.args[0]
    assert not r._background_tasks  # nothing spawned


@pytest.mark.asyncio
async def test_run_video_generate_mentions_queue_position():
    tc = MagicMock()
    tc.queue_video = AsyncMock(return_value={"queue_position": 4})
    r = _router(tc)
    ctx = _ctx(notify_channel=None)
    await r.run_video_generate(ctx, "job1")
    assert "queue position 4" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_video_generate_api_error():
    tc = MagicMock()
    tc.queue_video = AsyncMock(side_effect=TasksAPIError(409, "still collecting"))
    r = _router(tc)
    ctx = _ctx(notify_channel=None)
    await r.run_video_generate(ctx, "job1")
    assert "still collecting" in ctx.respond.await_args.args[0]
    assert not r._background_tasks


# --- run_video_refine ------------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_refine_proposes_apply():
    tc = MagicMock()
    tc.refine_video = AsyncMock(return_value={"message": "I'll slow scene 2", "can_apply": True})
    r = _router(tc)
    ncm = AsyncMock()
    ctx = _ctx(notify_channel_msg=ncm)
    await r.run_video_refine(ctx, "job1", "slow it down")
    ncm.assert_awaited_once()
    payload = ncm.await_args.args[0]
    assert "components" in payload and payload["components"]


@pytest.mark.asyncio
async def test_run_video_refine_plain_when_not_applicable():
    tc = MagicMock()
    tc.refine_video = AsyncMock(return_value={"message": "Need more detail", "can_apply": False})
    r = _router(tc)
    ctx = _ctx(notify_channel_msg=AsyncMock())
    await r.run_video_refine(ctx, "job1", "?")
    ctx.respond.assert_awaited()
    assert "Need more detail" in ctx.respond.await_args.args[0]


# --- run_video_list --------------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_list_empty():
    tc = MagicMock()
    tc.list_videos = AsyncMock(return_value={"videos": []})
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_list(ctx)
    assert "no videos" in ctx.respond.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_run_video_list_lines():
    tc = MagicMock()
    tc.list_videos = AsyncMock(return_value={"videos": [
        {"id": "a", "title": "Vid A", "status": "done", "output_available": True},
        {"id": "b", "title": None, "status": "rendering"},
    ]})
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_list(ctx)
    out = ctx.respond.await_args.args[0]
    assert "Vid A" in out and "(ready)" in out and "b" in out


# --- run_video_revert ------------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_revert_instant_delivers():
    tc = MagicMock()
    tc.revert_video = AsyncMock(return_value={"status": "reverted"})
    r = _router(tc)
    r._deliver_video = AsyncMock()
    ctx = _ctx(notify_channel=AsyncMock())
    await r.run_video_revert(ctx, "job1", 2)
    r._deliver_video.assert_awaited_once()
    assert not r._background_tasks


@pytest.mark.asyncio
async def test_run_video_revert_rerender_no_watcher_when_no_channel():
    tc = MagicMock()
    tc.revert_video = AsyncMock(return_value={"status": "queued"})
    r = _router(tc)
    ctx = _ctx(notify_channel=None)
    await r.run_video_revert(ctx, "job1", 2)
    ctx.respond.assert_awaited()
    assert not r._background_tasks
