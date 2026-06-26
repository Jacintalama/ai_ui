"""Tests for the shared video-studio opener and the /video new payload parser."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler


def _handler(email="u@x.com"):
    h = DiscordCommandHandler.__new__(DiscordCommandHandler)
    tc = MagicMock()
    tc.create_video_draft = AsyncMock(return_value={"id": "job1"})
    tc.add_video_screenshots_urls = AsyncMock(return_value={"count": 2})
    tc.get_video_voices = AsyncMock(return_value={"voices": []})
    tc.fetch_bytes = AsyncMock(return_value=b"x")
    router = MagicMock()
    router._tasks_client = tc
    router._resolve_email = AsyncMock(return_value=email)
    h.router = router
    discord = MagicMock()
    discord.edit_original = AsyncMock()
    discord.post_channel_file = AsyncMock()
    discord.post_channel_message = AsyncMock()
    h.discord = discord
    h._get_or_make_thread = AsyncMock(return_value="thread1")
    return h, router, discord


@pytest.mark.asyncio
async def test_open_video_studio_with_screenshots_creates_draft_and_adds_urls():
    h, router, discord = _handler()
    await h._open_video_studio(
        interaction_token="t", user_id="100", user_name="alice", channel_id="c",
        title="My Demo", prompt="walk the dashboard",
        screenshot_urls=["http://cdn/1.png", "http://cdn/2.png"])
    router._tasks_client.create_video_draft.assert_awaited_once_with(
        "u@x.com", "My Demo", "walk the dashboard", "clean_product_demo", "amy",
        render_mode="remotion", animation_preset="cursor_click")
    router._tasks_client.add_video_screenshots_urls.assert_awaited_once_with(
        "u@x.com", "job1", ["http://cdn/1.png", "http://cdn/2.png"])
    discord.post_channel_message.assert_awaited_once()
    content = discord.post_channel_message.await_args.args[1]
    # Pre-attached screenshots skip the source step and go straight to Describe.
    assert "2/12" in content
    assert "description" in content.lower()
    components = discord.post_channel_message.await_args.kwargs["components"]
    ids = [c.get("custom_id") for row in components for c in row["components"]]
    from handlers import video_panel as vp
    assert f"{vp.DETAILS_PREFIX}job1" in ids  # Describe-step button


@pytest.mark.asyncio
async def test_open_video_studio_without_screenshots_skips_add():
    h, router, discord = _handler()
    await h._open_video_studio(
        interaction_token="t", user_id="100", user_name="alice", channel_id="c",
        title="My Demo", prompt="desc", screenshot_urls=None)
    router._tasks_client.add_video_screenshots_urls.assert_not_called()
    content = discord.post_channel_message.await_args.args[1].lower()
    # The empty-draft entry posts the wizard Step 1 source-choice card.
    assert "how do you want to start" in content
    components = discord.post_channel_message.await_args.kwargs["components"]
    ids = [c.get("custom_id") for row in components for c in row["components"]]
    from handlers import video_panel as vp
    assert f"{vp.SRC_URL_PREFIX}job1" in ids
    assert f"{vp.SRC_SHOTS_PREFIX}job1" in ids


@pytest.mark.asyncio
async def test_open_video_studio_not_linked_posts_card_no_draft():
    h, router, discord = _handler(email=None)
    await h._open_video_studio(
        interaction_token="t", user_id="100", user_name="alice", channel_id="c",
        title="t", prompt="d", screenshot_urls=["http://cdn/1.png"])
    router._tasks_client.create_video_draft.assert_not_called()
    discord.edit_original.assert_awaited()  # the not-linked card


def test_parse_video_new_extracts_fields_and_urls():
    data = {
        "options": [{"name": "new", "type": 1, "options": [
            {"name": "description", "type": 3, "value": "walk the dashboard"},
            {"name": "title", "type": 3, "value": "My Demo"},
            {"name": "shot1", "type": 11, "value": "att1"},
        ]}],
        "resolved": {"attachments": {
            "att1": {"url": "http://cdn/1.png", "filename": "1.png",
                     "content_type": "image/png", "size": 10},
        }},
    }
    title, prompt, urls = DiscordCommandHandler._parse_video_new(data)
    assert title == "My Demo"
    assert prompt == "walk the dashboard"
    assert urls == ["http://cdn/1.png"]


def test_parse_video_new_defaults_title_from_description():
    data = {"options": [{"name": "new", "type": 1, "options": [
        {"name": "description", "type": 3, "value": "x" * 80},
    ]}], "resolved": {}}
    title, prompt, urls = DiscordCommandHandler._parse_video_new(data)
    assert title == "x" * 60
    assert prompt == "x" * 80
    assert urls == []


def test_parse_video_new_untitled_when_blank():
    data = {"options": [{"name": "new", "type": 1, "options": [
        {"name": "description", "type": 3, "value": "   "},
    ]}], "resolved": {}}
    title, prompt, urls = DiscordCommandHandler._parse_video_new(data)
    assert title == "Untitled video"
    assert prompt == ""


def _thread_handler():
    h = DiscordCommandHandler.__new__(DiscordCommandHandler)
    router = MagicMock()
    router.get_user_video_thread = AsyncMock(return_value=None)
    router.set_user_video_thread = AsyncMock()
    h.router = router
    discord = MagicMock()
    discord.add_thread_member = AsyncMock(return_value=True)
    discord.create_private_thread = AsyncMock(return_value="t-new")
    h.discord = discord
    return h, router, discord


@pytest.mark.asyncio
async def test_get_or_make_thread_reuses_live_thread():
    h, router, discord = _thread_handler()
    router.get_user_video_thread = AsyncMock(return_value="t-live")
    discord.add_thread_member = AsyncMock(return_value=True)
    tid = await h._get_or_make_thread("100", "chan", "alice", kind="video")
    assert tid == "t-live"
    discord.create_private_thread.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_make_thread_recreates_deleted_thread():
    """A stored thread the user deleted (add_thread_member -> False) is replaced
    with a fresh one instead of returning a dead '#unknown' link."""
    h, router, discord = _thread_handler()
    router.get_user_video_thread = AsyncMock(return_value="t-dead")
    discord.add_thread_member = AsyncMock(side_effect=[False, True])
    discord.create_private_thread = AsyncMock(return_value="t-new")
    tid = await h._get_or_make_thread("100", "chan", "alice", kind="video")
    assert tid == "t-new"
    discord.create_private_thread.assert_awaited_once()
    router.set_user_video_thread.assert_awaited_once_with("100", "t-new")


@pytest.mark.asyncio
async def test_get_or_make_thread_creates_when_none():
    h, router, discord = _thread_handler()
    router.get_user_video_thread = AsyncMock(return_value=None)
    discord.create_private_thread = AsyncMock(return_value="t-new")
    tid = await h._get_or_make_thread("100", "chan", "alice", kind="video")
    assert tid == "t-new"
    router.set_user_video_thread.assert_awaited_once_with("100", "t-new")


@pytest.mark.asyncio
async def test_set_video_draft_fields_includes_title_and_prompt():
    from clients.tasks import TasksClient
    tc = TasksClient(base_url="http://t")
    captured = {}

    async def fake_request(method, path, user_email, json=None):
        captured["json"] = json

        class R:
            def json(self_inner):
                return {"status": "ok"}
        return R()

    tc._request = fake_request
    await tc.set_video_draft_fields("u@x.com", "job1", title="T", prompt="P")
    assert captured["json"] == {"title": "T", "prompt": "P"}
