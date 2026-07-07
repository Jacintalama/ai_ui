"""Discord 'Schedule a video' flow: dashboard button, modal, template-select
confirm card, and the create path (kind='video' + video_config). Mirrors the
payload-builder style of test_schedule_interactions.py."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.app_builder_panel import (
    SCHED_CANCEL_PREFIX, SCHED_CONFIRM_PREFIX, SCHED_NEWVID_ID, SCHED_VIDMODAL_ID,
    SCHED_VIDTPL_PREFIX, SCHED_VID_URL_INPUT, SCHED_VID_WHAT_INPUT,
    SCHED_VID_WHEN_INPUT, build_schedules_dashboard,
    build_video_schedule_confirm_components, build_video_schedule_modal,
)

_TPLS = [{"key": "walkthrough", "emoji": "X", "name": "Website Walkthrough",
          "desc": "tour", "style": "clean_product_demo", "prompt": "p"}]


def _ids(rows):
    return [c.get("custom_id") for row in rows for c in row.get("components", [])]


def test_dashboard_has_video_button():
    panel = build_schedules_dashboard([])
    assert SCHED_NEWVID_ID in _ids(panel["components"])


def test_video_modal_inputs_and_custom_id():
    modal = build_video_schedule_modal()
    assert modal["custom_id"] == SCHED_VIDMODAL_ID
    inputs = [c for row in modal["components"] for c in row["components"]]
    ids = [i["custom_id"] for i in inputs]
    assert ids == [SCHED_VID_URL_INPUT, SCHED_VID_WHAT_INPUT, SCHED_VID_WHEN_INPUT]
    by_id = {i["custom_id"]: i for i in inputs}
    assert by_id[SCHED_VID_URL_INPUT]["required"] is True
    assert by_id[SCHED_VID_WHAT_INPUT]["required"] is False
    assert by_id[SCHED_VID_WHEN_INPUT]["required"] is True


def test_video_confirm_card_has_template_select_and_buttons():
    rows = build_video_schedule_confirm_components("tok1", _TPLS)
    ids = _ids(rows)
    assert f"{SCHED_VIDTPL_PREFIX}tok1" in ids
    assert f"{SCHED_CONFIRM_PREFIX}tok1" in ids
    assert f"{SCHED_CANCEL_PREFIX}tok1" in ids
    select = rows[0]["components"][0]
    values = [o["value"] for o in select["options"]]
    assert values[0] == "none"
    assert "walkthrough" in values
    assert select["options"][0]["default"] is True


# ── interaction tests (mirror test_schedule_interactions.py's fixtures) ─────
from handlers.discord_commands import DiscordCommandHandler, MODAL, CHANNEL_MESSAGE_WITH_SOURCE


def _handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    discord.create_private_thread = AsyncMock(return_value="thread-9")
    discord.add_thread_member = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=discord, command_router=router)


def _component(custom_id, values=None, *, user_id="100"):
    data = {"custom_id": custom_id}
    if values is not None:
        data["values"] = values
    return {"type": 3, "id": "i", "token": "t", "data": data,
            "member": {"user": {"id": user_id, "username": "alice"}}, "channel_id": "chan-1"}


def _vid_submit(url, what, when, *, token="tok1", channel_id="chan-1", user_id="100"):
    return {"type": 5, "id": "i", "token": token, "channel_id": channel_id,
            "member": {"user": {"id": user_id, "username": "alice"}},
            "data": {"custom_id": SCHED_VIDMODAL_ID, "components": [
                {"type": 1, "components": [{"type": 4, "custom_id": SCHED_VID_URL_INPUT, "value": url}]},
                {"type": 1, "components": [{"type": 4, "custom_id": SCHED_VID_WHAT_INPUT, "value": what}]},
                {"type": 1, "components": [{"type": 4, "custom_id": SCHED_VID_WHEN_INPUT, "value": when}]},
            ]}}


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


# Test A: SCHED_NEWVID_ID component -> response type 9 (MODAL) with
#   data.custom_id == SCHED_VIDMODAL_ID.
@pytest.mark.asyncio
async def test_newvid_button_opens_video_modal():
    resp = await _handler(MagicMock()).handle_interaction(_component(SCHED_NEWVID_ID))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == SCHED_VIDMODAL_ID


# Test B: video modal submit with bad URL -> ephemeral error mentioning http.
@pytest.mark.asyncio
async def test_video_modal_submit_bad_url_shows_error():
    resp = await _handler(MagicMock()).handle_interaction(
        _vid_submit("not-a-url", "", "every morning"))
    assert resp["type"] == CHANNEL_MESSAGE_WITH_SOURCE
    assert resp["data"]["flags"] == 64
    assert "http" in resp["data"]["content"].lower()


# Test C: video modal submit with good URL + "every morning" -> response
#   contains build_video_schedule_confirm_components ids and a
#   _pending_schedules entry with kind == "video" and video_config.url set.
@pytest.mark.asyncio
async def test_video_modal_submit_good_url_shows_confirm_card_and_parks_pending():
    handler = _handler(MagicMock())
    resp = await handler.handle_interaction(
        _vid_submit("https://example.com", "show the pricing page", "every morning"))
    assert resp["type"] == CHANNEL_MESSAGE_WITH_SOURCE
    assert resp["data"]["flags"] == 64
    ids = [c["custom_id"] for row in resp["data"]["components"] for c in row["components"]]
    assert any(i.startswith(SCHED_VIDTPL_PREFIX) for i in ids)
    assert any(i.startswith(SCHED_CONFIRM_PREFIX) for i in ids)
    assert any(i.startswith(SCHED_CANCEL_PREFIX) for i in ids)
    assert len(handler._pending_schedules) == 1
    token, pending = next(iter(handler._pending_schedules.items()))
    assert pending["kind"] == "video"
    assert pending["video_config"]["url"] == "https://example.com"
    assert pending["video_config"]["prompt"] == "show the pricing page"
    assert pending["video_config"]["template"] == ""


# Test D: SCHED_VIDTPL_PREFIX select with value "walkthrough" mutates the
#   pending entry's video_config["template"]; value "none" clears it.
@pytest.mark.asyncio
async def test_vidtpl_select_mutates_pending_video_config_template():
    handler = _handler(MagicMock())
    handler._pending_schedules["tok1"] = {
        "name": "n", "cron": "0 8 * * *", "prompt": "p", "human": "daily",
        "run_once": False, "kind": "video",
        "video_config": {"url": "https://example.com", "prompt": "", "template": "", "title": "t"},
    }
    resp = await handler.handle_interaction(
        _component(f"{SCHED_VIDTPL_PREFIX}tok1", values=["walkthrough"]))
    assert resp["type"] == 6  # DEFERRED_UPDATE_MESSAGE
    assert handler._pending_schedules["tok1"]["video_config"]["template"] == "walkthrough"

    resp = await handler.handle_interaction(
        _component(f"{SCHED_VIDTPL_PREFIX}tok1", values=["none"]))
    assert resp["type"] == 6
    assert handler._pending_schedules["tok1"]["video_config"]["template"] == ""


@pytest.mark.asyncio
async def test_vidtpl_select_unknown_token_is_graceful():
    handler = _handler(MagicMock())
    resp = await handler.handle_interaction(
        _component(f"{SCHED_VIDTPL_PREFIX}ghost", values=["walkthrough"]))
    assert resp["type"] == 6  # ack, no crash, no KeyError


# Test E: confirm path passes kind/video_config to run_schedule_create
#   (mock router.run_schedule_create; drive _create_pending_schedule).
@pytest.mark.asyncio
async def test_confirm_video_schedule_passes_kind_and_video_config():
    captured = {}

    async def fake_create(ctx, *, name, cron, prompt, delivery_channel_id=None,
                           run_once=False, kind="agent", video_config=None):
        captured.update(name=name, cron=cron, prompt=prompt,
                        delivery=delivery_channel_id, kind=kind,
                        video_config=video_config)
    router = MagicMock()
    router.run_schedule_create = fake_create
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock(return_value=True)
    handler = _handler(router)

    handler._pending_schedules["tok1"] = {
        "name": "daily: video of example.com", "cron": "0 8 * * *",
        "prompt": "Video walkthrough of https://example.com", "human": "daily",
        "run_once": False, "kind": "video",
        "video_config": {"url": "https://example.com", "prompt": "", "template": "walkthrough",
                         "title": "example.com walkthrough"},
    }
    resp = await handler.handle_interaction(_component(f"{SCHED_CONFIRM_PREFIX}tok1"))
    assert resp["type"] == 5 and resp["data"]["flags"] == 64
    await _drain()
    assert captured["kind"] == "video"
    assert captured["video_config"]["url"] == "https://example.com"
    assert captured["video_config"]["template"] == "walkthrough"
    assert captured["cron"] == "0 8 * * *"


@pytest.mark.asyncio
async def test_confirm_agent_schedule_still_defaults_kind_agent():
    # The shared confirm path must tolerate pending dicts without kind/video_config
    # (the plain agent-schedule flow never sets them).
    captured = {}

    async def fake_create(ctx, *, name, cron, prompt, delivery_channel_id=None,
                           run_once=False, kind="agent", video_config=None):
        captured.update(kind=kind, video_config=video_config)
    router = MagicMock()
    router.run_schedule_create = fake_create
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock(return_value=True)
    handler = _handler(router)

    handler._pending_schedules["tok1"] = {
        "name": "daily: do things", "cron": "0 8 * * *", "prompt": "do things",
        "human": "daily", "run_once": False,
    }
    await handler.handle_interaction(_component(f"{SCHED_CONFIRM_PREFIX}tok1"))
    await _drain()
    assert captured["kind"] == "agent"
    assert captured["video_config"] is None
