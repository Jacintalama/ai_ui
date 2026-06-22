"""Unit tests for the drop-to-add video screenshot intake. No discord.py:
extract_image_drop reads attributes off plain fakes, and VideoThreadIntake is
fed primitives, so these run without the gateway library installed."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from handlers.video_intake import VideoThreadIntake, extract_image_drop


def _intake(channel_id="999", channel_name="video-generation"):
    router = MagicMock()
    router.run_video_add = AsyncMock()
    discord = MagicMock()
    discord.post_channel_message = AsyncMock()
    intake = VideoThreadIntake(router, discord, video_channel_id=channel_id,
                               video_channel_name=channel_name)
    return intake, router, discord


def _img(url, ct="image/png", fn="shot.png"):
    return {"url": url, "content_type": ct, "filename": fn}


# --- VideoThreadIntake.handle_image_drop ---

@pytest.mark.asyncio
async def test_image_in_video_thread_calls_run_video_add():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread1",
        channel_name="aiui-video-alice", is_thread=True,
        parent_channel_id="999", parent_channel_name="video-generation",
        attachments=[_img("http://cdn/1.png"), _img("http://cdn/2.png")])
    router.run_video_add.assert_awaited_once()
    ctx, urls = router.run_video_add.await_args.args
    assert urls == ["http://cdn/1.png", "http://cdn/2.png"]
    assert ctx.user_id == "100"
    assert ctx.platform == "discord"
    discord.post_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_non_image_attachment_ignored():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread1",
        channel_name="t", is_thread=True, parent_channel_id="999",
        parent_channel_name="video-generation",
        attachments=[{"url": "http://cdn/x.pdf",
                      "content_type": "application/pdf", "filename": "x.pdf"}])
    router.run_video_add.assert_not_called()
    discord.post_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_image_in_main_channel_posts_nudge():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="999",
        channel_name="video-generation", is_thread=False,
        parent_channel_id=None, parent_channel_name=None,
        attachments=[_img("http://cdn/1.png")])
    router.run_video_add.assert_not_called()
    discord.post_channel_message.assert_awaited_once()
    cid, msg = discord.post_channel_message.await_args.args
    assert cid == "999"
    assert "New video" in msg


@pytest.mark.asyncio
async def test_image_in_unrelated_thread_ignored():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread2",
        channel_name="aiui-apps-alice", is_thread=True,
        parent_channel_id="555", parent_channel_name="app-builder",
        attachments=[_img("http://cdn/1.png")])
    router.run_video_add.assert_not_called()
    discord.post_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_attachments_forwards_only_images():
    intake, router, discord = _intake()
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="thread1",
        channel_name="t", is_thread=True, parent_channel_id="999",
        parent_channel_name="video-generation",
        attachments=[_img("http://cdn/a.png"),
                     {"url": "http://cdn/b.pdf",
                      "content_type": "application/pdf", "filename": "b.pdf"},
                     _img("http://cdn/c.jpg", ct=None, fn="c.JPG")])
    router.run_video_add.assert_awaited_once()
    _, urls = router.run_video_add.await_args.args
    assert urls == ["http://cdn/a.png", "http://cdn/c.jpg"]


@pytest.mark.asyncio
async def test_channel_match_by_name_when_no_id():
    intake, router, discord = _intake(channel_id=None, channel_name="video-generation")
    await intake.handle_image_drop(
        author_id="100", author_name="alice", channel_id="threadX",
        channel_name="t", is_thread=True, parent_channel_id="anything",
        parent_channel_name="Video-Generation",
        attachments=[_img("http://cdn/1.png")])
    router.run_video_add.assert_awaited_once()


# --- extract_image_drop ---

def test_extract_thread_message():
    msg = SimpleNamespace(
        author=SimpleNamespace(id=100, bot=False, name="alice", display_name="Alice"),
        attachments=[SimpleNamespace(url="http://cdn/1.png",
                                     content_type="image/png", filename="1.png")],
        channel=SimpleNamespace(id=555, name="aiui-video-alice",
                                parent_id=999, parent=SimpleNamespace(name="video-generation")),
    )
    info = extract_image_drop(msg)
    assert info["author_id"] == "100"
    assert info["author_name"] == "Alice"
    assert info["channel_id"] == "555"
    assert info["is_thread"] is True
    assert info["parent_channel_id"] == "999"
    assert info["parent_channel_name"] == "video-generation"
    assert info["attachments"][0]["url"] == "http://cdn/1.png"


def test_extract_plain_channel_message():
    msg = SimpleNamespace(
        author=SimpleNamespace(id=100, bot=False, name="alice", display_name="Alice"),
        attachments=[SimpleNamespace(url="http://cdn/1.png",
                                     content_type="image/png", filename="1.png")],
        channel=SimpleNamespace(id=999, name="video-generation"),  # no parent_id
    )
    info = extract_image_drop(msg)
    assert info["is_thread"] is False
    assert info["parent_channel_id"] is None
    assert info["channel_id"] == "999"


def test_extract_no_attachments_returns_none():
    msg = SimpleNamespace(
        author=SimpleNamespace(id=100, bot=False, name="alice", display_name="Alice"),
        attachments=[],
        channel=SimpleNamespace(id=999, name="video-generation"),
    )
    assert extract_image_drop(msg) is None
