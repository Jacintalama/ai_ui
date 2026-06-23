"""Routing tests for the #video-generation channel (Task B5).

Exercises DiscordCommandHandler's dispatch of the aiuivid:* components/modals
and the /video slash command into the CommandRouter.run_video_* runners. The
runners themselves are faked (recorded) — this verifies wiring, ack types, and
that watcher-bearing actions get a bound notify_channel.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers import video_panel as vid

# Discord callback types
MODAL = 9
DEFERRED_CHANNEL_MESSAGE = 5
DEFERRED_UPDATE_MESSAGE = 6


def _router():
    """Fake CommandRouter with the run_video_* coroutines as recording mocks."""
    r = MagicMock()
    r.run_video_add = AsyncMock()
    r.run_video_list = AsyncMock()
    r.run_video_set_field = AsyncMock()
    r.run_video_generate = AsyncMock()
    r.run_video_apply = AsyncMock()
    r.run_video_revert = AsyncMock()
    r.run_video_refine = AsyncMock()
    r.run_video_capture = AsyncMock()
    return r


def _handler(router, *, no_notifiers=True):
    """Real handler (real _spawn / _bg_tasks) with a stub discord. By default
    _channel_notifiers is stubbed to (None, None) so routing tests don't depend
    on delivery; pass no_notifiers=False to keep the real notifier closures."""
    h = DiscordCommandHandler(discord_client=MagicMock(), command_router=router)
    if no_notifiers:
        h._channel_notifiers = lambda channel_id: (None, None)
    return h


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_new_button_opens_studio_deferred():
    """Clicking New video ACKs ephemeral-deferred and opens the studio with an
    EMPTY draft (title 'Untitled video', blank prompt) in the background."""
    router = _router()
    router._resolve_email = AsyncMock(return_value="u@x.com")
    tc = MagicMock()
    tc.create_video_draft = AsyncMock(return_value={"id": "jobN"})
    tc.get_video_voices = AsyncMock(return_value={"voices": []})
    tc.fetch_bytes = AsyncMock(return_value=b"mp3")
    router._tasks_client = tc
    handler = _handler(router)
    discord = handler.discord
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    discord.post_channel_file = AsyncMock(return_value=True)
    handler._get_or_make_thread = AsyncMock(return_value="thread-n")
    payload = {"type": 3, "id": "i", "token": "t", "channel_id": "c",
               "member": {"user": {"id": "100", "username": "alice"}},
               "data": {"custom_id": vid.NEW_ID}}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    tc.create_video_draft.assert_awaited_once_with(
        "u@x.com", "Untitled video", "", "clean_product_demo", "amy")
    assert discord.post_channel_message.await_args.args[0] == "thread-n"


@pytest.mark.asyncio
async def test_video_add_dispatches_urls_in_order():
    router = _router()
    handler = _handler(router)
    payload = {
        "type": 2, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {
            "name": "video",
            "options": [{"name": "add", "type": 1}],
            "resolved": {"attachments": {
                "1": {"url": "http://cdn/1.png", "filename": "a.png"},
                "2": {"url": "http://cdn/2.png", "filename": "b.png"},
            }},
        },
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    router.run_video_add.assert_awaited_once()
    _ctx, urls = router.run_video_add.await_args.args
    assert urls == ["http://cdn/1.png", "http://cdn/2.png"]


@pytest.mark.asyncio
async def test_video_list_dispatches_run_video_list():
    router = _router()
    handler = _handler(router)
    payload = {
        "type": 2, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"name": "video", "options": [{"name": "list", "type": 1}]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    await _drain()
    router.run_video_list.assert_awaited_once()
    router.run_video_add.assert_not_awaited()


@pytest.mark.asyncio
async def test_style_select_sets_field():
    router = _router()
    handler = _handler(router)
    payload = {
        "type": 3, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.STYLE_PREFIX}j1", "values": ["cinematic"]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_UPDATE_MESSAGE
    await _drain()
    router.run_video_set_field.assert_awaited_once()
    args = router.run_video_set_field.await_args
    assert args.args[1] == "j1"
    assert args.kwargs == {"style": "cinematic"}


@pytest.mark.asyncio
async def test_voice_select_sets_field():
    router = _router()
    handler = _handler(router)
    payload = {
        "type": 3, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.VOICE_PREFIX}j7", "values": ["amy"]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_UPDATE_MESSAGE
    await _drain()
    args = router.run_video_set_field.await_args
    assert args.args[1] == "j7"
    assert args.kwargs == {"voice": "amy"}


@pytest.mark.asyncio
async def test_empty_select_is_noop():
    router = _router()
    handler = _handler(router)
    payload = {
        "type": 3, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.STYLE_PREFIX}j1", "values": []},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_UPDATE_MESSAGE
    await _drain()
    router.run_video_set_field.assert_not_awaited()


@pytest.mark.asyncio
async def test_refine_button_opens_refine_modal():
    handler = _handler(_router())
    payload = {"type": 3, "id": "i", "token": "t", "channel_id": "c",
               "member": {"user": {"id": "100", "username": "alice"}},
               "data": {"custom_id": f"{vid.REFINE_PREFIX}j1"}}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == f"{vid.REFINE_MODAL_PREFIX}j1"  # "aiuivid:refinemodal:j1"


@pytest.mark.asyncio
async def test_generate_dispatches_and_binds_notify_channel():
    """Generate must route through a ctx with notify_channel bound so the render
    watcher can post the finished video into the thread."""
    router = _router()
    handler = _handler(router, no_notifiers=False)  # real notifier closures
    payload = {
        "type": 3, "id": "i", "token": "t", "channel_id": "thread-1",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.GENERATE_PREFIX}j1"},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    router.run_video_generate.assert_awaited_once()
    ctx, job_id = router.run_video_generate.await_args.args
    assert job_id == "j1"
    assert ctx.notify_channel is not None  # watcher gate
    assert ctx.notify_channel_msg is not None  # controls poster


@pytest.mark.asyncio
async def test_version_select_dispatches_revert():
    router = _router()
    handler = _handler(router)
    payload = {
        "type": 3, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.VERSION_PREFIX}j1", "values": ["2"]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    await _drain()
    router.run_video_revert.assert_awaited_once()
    ctx, job_id, version_no = router.run_video_revert.await_args.args
    assert job_id == "j1" and version_no == 2


@pytest.mark.asyncio
async def test_refine_modal_submit_dispatches_with_notify_channel_msg():
    router = _router()
    handler = _handler(router, no_notifiers=False)
    payload = {
        "type": 5, "id": "i", "token": "t", "channel_id": "thread-1",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.REFINE_MODAL_PREFIX}j1", "components": [
            {"type": 1, "components": [
                {"type": 4, "custom_id": vid.REFINE_INPUT, "value": "slow scene 2"}]},
        ]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    await _drain()
    router.run_video_refine.assert_awaited_once()
    ctx, job_id, change = router.run_video_refine.await_args.args
    assert job_id == "j1" and change == "slow scene 2"
    assert ctx.notify_channel_msg is not None  # proposal poster


@pytest.mark.asyncio
async def test_capture_button_opens_capture_modal():
    handler = _handler(_router())
    payload = {"type": 3, "id": "i", "token": "t", "channel_id": "c",
               "member": {"user": {"id": "100", "username": "alice"}},
               "data": {"custom_id": f"{vid.CAPTURE_PREFIX}j1"}}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == f"{vid.CAPTURE_MODAL_PREFIX}j1"


@pytest.mark.asyncio
async def test_capture_modal_submit_dispatches_capture():
    router = _router()
    handler = _handler(router)
    handler.discord.edit_original = AsyncMock(return_value=True)
    payload = {
        "type": 5, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.CAPTURE_MODAL_PREFIX}j1", "components": [
            {"type": 1, "components": [
                {"type": 4, "custom_id": vid.URL_INPUT, "value": "https://s.com"}]},
        ]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    router.run_video_capture.assert_awaited_once()
    ctx, url = router.run_video_capture.await_args.args
    assert url == "https://s.com"


@pytest.mark.asyncio
async def test_details_modal_submit_routes_to_set_details():
    """Add-title-&-description modal submit ACKs ephemeral-deferred and routes
    to run_video_set_details with the parsed job id + title/prompt."""
    router = _router()
    router.run_video_set_details = AsyncMock()
    handler = _handler(router)
    handler.discord.edit_original = AsyncMock(return_value=True)
    payload = {
        "type": 5, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.DETAILS_MODAL_PREFIX}job7", "components": [
            {"type": 1, "components": [
                {"type": 4, "custom_id": vid.TITLE_INPUT, "value": "Dash"}]},
            {"type": 1, "components": [
                {"type": 4, "custom_id": vid.PROMPT_INPUT, "value": "walk it"}]},
        ]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    router.run_video_set_details.assert_awaited_once()
    args, kwargs = router.run_video_set_details.await_args
    assert args[1] == "job7"
    assert kwargs == {"title": "Dash", "prompt": "walk it"}
