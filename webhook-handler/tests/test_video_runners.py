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
async def test_run_video_add_first_add_posts_choice_card():
    """First add (draft had 0 screenshots) -> posts build_choice_components."""
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job1", "screenshot_count": 0})
    tc.add_video_screenshots_urls = AsyncMock(return_value={"count": 2})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    urls = ["http://cdn/1.png", "http://cdn/2.png"]
    await r.run_video_add(ctx, urls)
    tc.add_video_screenshots_urls.assert_awaited_once_with("u@x.com", "job1", urls)
    rc.assert_awaited_once()
    msg, components = rc.await_args.args
    assert "2/12" in msg
    # Should post the choice card: Generate now (gennow) + Add direction (details)
    assert isinstance(components, list) and components
    all_ids = [c.get("custom_id") for row in components for c in row.get("components", [])]
    assert any("aiuivid:gennow:job1" == cid for cid in all_ids)
    assert any("aiuivid:details:job1" == cid for cid in all_ids)


@pytest.mark.asyncio
async def test_run_video_add_subsequent_add_no_describe_repost():
    """Subsequent add (draft already had screenshots) -> just the N/12 text, no Describe card."""
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job1", "screenshot_count": 2})
    tc.add_video_screenshots_urls = AsyncMock(return_value={"count": 3})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    urls = ["http://cdn/3.png"]
    await r.run_video_add(ctx, urls)
    # respond_components should NOT have been called (no new wizard card)
    rc.assert_not_called()
    # plain text respond should have been called with count progress
    ctx.respond.assert_awaited()
    assert "3/12" in ctx.respond.await_args.args[0]


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
async def test_run_video_set_details_patches_and_posts_generate_step():
    """set_details saves fields and posts the Generate step card when respond_components is wired."""
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock(return_value={"status": "ok"})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    await r.run_video_set_details(ctx, "job1", title="T", prompt="P")
    tc.set_video_draft_fields.assert_awaited_once_with("u@x.com", "job1", title="T", prompt="P")
    # Spinner must always be resolved first (regression guard: never skip ctx.respond)
    ctx.respond.assert_awaited()
    # Should post Generate step components
    rc.assert_awaited_once()
    msg, components = rc.await_args.args
    assert isinstance(components, list) and components
    all_ids = [c.get("custom_id") for row in components for c in row.get("components", [])]
    assert any("aiuivid:generate:job1" == cid for cid in all_ids)
    assert any("aiuivid:options:job1" == cid for cid in all_ids)


@pytest.mark.asyncio
async def test_run_video_set_details_patches_and_confirms_text():
    """set_details always calls ctx.respond with a confirmation (even when no poster)."""
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
    assert "Vid A" in out and "done" in out and "b" in out


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


# --- run_video_capture ------------------------------------------------------ #

@pytest.mark.asyncio
async def test_run_video_capture_captures_and_posts_describe_step():
    """After a successful capture, posts the Describe step card (not the Generate row)."""
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job9"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    await r.run_video_capture(ctx, "https://mysite.com")
    tc.capture_video_screenshots.assert_awaited_once_with("u@x.com", "job9", "https://mysite.com")
    rc.assert_awaited_once()
    msg, components = rc.await_args.args
    assert "4/12" in msg
    # Should post Describe step (Add description button) not Generate row
    assert isinstance(components, list) and components
    all_ids = [c.get("custom_id") for row in components for c in row.get("components", [])]
    assert any("aiuivid:details:job9" == cid for cid in all_ids)


@pytest.mark.asyncio
async def test_run_video_capture_no_draft_prompts_new_video():
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value=None)
    r = _router(tc)
    ctx = _ctx(respond_components=AsyncMock())
    await r.run_video_capture(ctx, "https://mysite.com")
    ctx.respond.assert_awaited()
    assert "New video" in ctx.respond.await_args.args[0]
    tc.capture_video_screenshots.assert_not_called()


@pytest.mark.asyncio
async def test_run_video_capture_unlinked():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    ctx = _ctx()
    await r.run_video_capture(ctx, "https://mysite.com")
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_video_capture_api_error_offers_fallback():
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job9"})
    tc.capture_video_screenshots = AsyncMock(side_effect=TasksAPIError(502, "couldn't capture site"))
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_capture(ctx, "https://mysite.com")
    msgs = [call.args[0] for call in ctx.respond.await_args_list]
    assert any("drag screenshots" in m.lower() for m in msgs)


# --- run_video_gennow ------------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_gennow_sets_remotion_then_generates():
    """run_video_gennow forces Remotion + cursor-click, then queues the video."""
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock()
    tc.queue_video = AsyncMock(return_value={"queue_position": 0})
    r = _router(tc)
    ctx = _ctx(notify_channel=None)  # no watcher spawned - keeps test hermetic
    await r.run_video_gennow(ctx, "job-1")
    tc.set_video_draft_fields.assert_awaited()
    assert tc.set_video_draft_fields.await_args.kwargs.get("render_mode") == "remotion"
    assert tc.set_video_draft_fields.await_args.kwargs.get("animation_preset") == "cursor_click"
    tc.queue_video.assert_awaited()
    # ordering: set_video_draft_fields must be awaited before queue_video
    names = [c[0] for c in tc.mock_calls]
    assert names.index("set_video_draft_fields") < names.index("queue_video")


@pytest.mark.asyncio
async def test_run_video_capture_posts_choice_card():
    """After a successful capture, posts the choice card with Generate-now button."""
    tc = MagicMock()
    tc.get_current_video_draft = AsyncMock(return_value={"id": "job9"})
    tc.capture_video_screenshots = AsyncMock(return_value={"count": 4})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    await r.run_video_capture(ctx, "https://mysite.com")
    rc.assert_awaited_once()
    msg, components = rc.await_args.args
    assert isinstance(components, list) and components
    all_ids = [c.get("custom_id") for row in components for c in row.get("components", [])]
    # Choice card must have the Generate-now button (not just the describe/details button)
    assert any("aiuivid:gennow:job9" == cid for cid in all_ids)


# --- run_video_apply_template ----------------------------------------------- #

@pytest.mark.asyncio
async def test_run_video_apply_template_sets_style_and_prompt():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock(return_value={"status": "ok"})
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_apply_template(ctx, "job1", "walkthrough")
    tc.set_video_draft_fields.assert_awaited_once()
    kwargs = tc.set_video_draft_fields.await_args.kwargs
    assert kwargs["style"] == "clean_product_demo"
    assert "guided tour" in kwargs["prompt"]


@pytest.mark.asyncio
async def test_run_video_apply_template_custom_is_noop():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock()
    r = _router(tc)
    await r.run_video_apply_template(_ctx(), "job1", "custom")
    tc.set_video_draft_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_video_apply_template_unknown_key_is_noop():
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock()
    r = _router(tc)
    await r.run_video_apply_template(_ctx(), "job1", "nope")
    tc.set_video_draft_fields.assert_not_awaited()


# ---------------------------------------------------------------------------
# My-videos manage flow (list select + menu + delete + retry)

import asyncio  # noqa: E402
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_video_list_posts_per_video_buttons_and_clean_labels():
    tc = MagicMock()
    tc.list_videos = AsyncMock(return_value={"videos": [
        {"id": "j1", "title": "Mine", "status": "collecting"},
        {"id": "j2", "title": "Done one", "status": "done",
         "share_url": "https://x/v.mp4"}]})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    await r.run_video_list(ctx)
    # Intro line goes through plain respond.
    assert "Your videos" in ctx.respond.await_args_list[0].args[0]
    # Each video gets its own message with its own buttons, no dropdown step.
    assert rc.await_count == 2
    msg1, rows1 = rc.await_args_list[0].args
    assert "draft (never started)" in msg1 and "collecting" not in msg1
    ids1 = [c.get("custom_id") for row in rows1 for c in row.get("components", [])]
    assert ids1 == ["aiuivid:del:j1"]
    msg2, rows2 = rc.await_args_list[1].args
    flat2 = [c for row in rows2 for c in row["components"]]
    assert any(c.get("url") == "https://x/v.mp4" for c in flat2)
    assert any(c.get("custom_id") == "aiuivid:del:j2" for c in flat2)


@pytest.mark.asyncio
async def test_run_video_menu_done_posts_watch_and_delete():
    tc = MagicMock()
    tc.get_video = AsyncMock(return_value={
        "id": "j1", "title": "Mine", "status": "done",
        "share_url": "https://x/v.mp4"})
    r = _router(tc)
    rc = AsyncMock()
    ctx = _ctx(respond_components=rc)
    await r.run_video_menu(ctx, "j1")
    header, rows = rc.await_args.args
    assert "done" in header
    flat = [c for row in rows for c in row["components"]]
    assert any(c.get("url") == "https://x/v.mp4" for c in flat)
    assert any(c.get("custom_id") == "aiuivid:del:j1" for c in flat)


@pytest.mark.asyncio
async def test_run_video_delete_deletes_and_confirms():
    tc = MagicMock()
    tc.delete_video = AsyncMock(return_value={"status": "deleted"})
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_delete(ctx, "j1")
    tc.delete_video.assert_awaited_once_with("u@x.com", "j1")
    assert "Deleted" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_video_delete_409_reports_rendering():
    tc = MagicMock()
    tc.delete_video = AsyncMock(side_effect=TasksAPIError(409, "mid-render"))
    r = _router(tc)
    ctx = _ctx()
    await r.run_video_delete(ctx, "j1")
    assert "rendering right now" in ctx.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_run_video_retry_requeues_and_watches():
    tc = MagicMock()
    tc.retry_video = AsyncMock(return_value={"status": "queued"})
    r = _router(tc)
    r._watch_video = AsyncMock()
    nc = AsyncMock()
    ctx = _ctx(notify_channel=nc)
    await r.run_video_retry(ctx, "j1")
    tc.retry_video.assert_awaited_once_with("u@x.com", "j1")
    await asyncio.gather(*r._background_tasks)
    r._watch_video.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_video_retry_conflict_is_clean():
    tc = MagicMock()
    tc.retry_video = AsyncMock(side_effect=TasksAPIError(409, "Only a failed video can be retried"))
    r = _router(tc)
    r._watch_video = AsyncMock()
    ctx = _ctx(notify_channel=AsyncMock())
    await r.run_video_retry(ctx, "j1")
    r._watch_video.assert_not_awaited()
    assert "Couldn't retry" in ctx.respond.await_args.args[0]
