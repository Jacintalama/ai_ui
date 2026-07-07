"""Slack "Schedule a video" flow: modal builder + interaction handling.

Mirrors test_slack_schedule_panel.py (builder shape) and
test_slack_schedule_interactions.py (view/state fixture style, router mock).
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.slack_schedule_panel import (
    SCHED_VIDEO_MODAL_ID,
    SCHED_VID_URL_BLOCK_ID,
    SCHED_VID_URL_INPUT_ID,
    SCHED_VID_TPL_BLOCK_ID,
    SCHED_VID_TPL_ACTION_ID,
    SCHED_VID_WHAT_BLOCK_ID,
    SCHED_VID_WHAT_INPUT_ID,
    build_schedule_modal,
    build_video_schedule_modal,
    sample_view_state,
)
from handlers.app_builder_panel import SCHED_NEWVID_ID
from handlers.slack_interactions import SlackInteractionsHandler

_TPLS = [{"key": "walkthrough", "emoji": "X", "name": "Website Walkthrough",
          "desc": "tour", "style": "clean_product_demo", "prompt": "p"}]


def _block(modal, block_id):
    return next(b for b in modal["blocks"] if b.get("block_id") == block_id)


# --- Step 1: builder tests ---

def test_video_modal_callback_and_inputs():
    modal = build_video_schedule_modal(_TPLS)
    assert modal["callback_id"] == SCHED_VIDEO_MODAL_ID
    url = _block(modal, "sched_vid_url")
    assert url["element"]["action_id"] == "sched_vid_url_input"
    tpl = _block(modal, "sched_vid_tpl")
    assert tpl["optional"] is True
    assert [o["value"] for o in tpl["element"]["options"]] == ["walkthrough"]
    what = _block(modal, "sched_vid_what")
    assert what["optional"] is True


def test_video_modal_shares_when_pickers_with_agent_modal():
    agent = build_schedule_modal()
    video = build_video_schedule_modal(_TPLS)
    agent_when = [b["block_id"] for b in agent["blocks"]
                  if b.get("block_id", "").startswith(("sched_repeat", "sched_time",
                                                        "sched_weekday", "sched_date"))]
    video_when = [b["block_id"] for b in video["blocks"]
                  if b.get("block_id", "").startswith(("sched_repeat", "sched_time",
                                                        "sched_weekday", "sched_date"))]
    assert agent_when == video_when and agent_when


# --- Step 4: interaction tests ---

def _handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _sched_router():
    router = MagicMock()
    router._background_tasks = set()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._not_linked_text = MagicMock(return_value="not-linked msg")
    router._tasks_client = MagicMock()
    router._tasks_client.create_schedule = AsyncMock(return_value={"id": 11})
    return router


def _block_actions_payload(action_id: str, user_id: str = "U1") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-vid",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": "C-panel"},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
    }


def _video_create_payload(url: str, *, repeat: str = "daily", time: str = "09:00",
                          weekday=None, date=None, what: str = "",
                          tpl_key: str = "", user_id: str = "U1") -> dict:
    """Video create-modal submit using the native date/time pickers, mirroring
    _picker_create_payload in test_slack_schedule_interactions.py."""
    state = sample_view_state(repeat, time=time, weekday=weekday, date=date)
    state[SCHED_VID_URL_BLOCK_ID] = {SCHED_VID_URL_INPUT_ID: {"value": url}}
    state[SCHED_VID_WHAT_BLOCK_ID] = {SCHED_VID_WHAT_INPUT_ID: {"value": what}}
    if tpl_key:
        state[SCHED_VID_TPL_BLOCK_ID] = {SCHED_VID_TPL_ACTION_ID: {
            "selected_option": {"value": tpl_key}}}
    return {
        "type": "view_submission",
        "user": {"id": user_id, "username": "tester"},
        "view": {"callback_id": SCHED_VIDEO_MODAL_ID, "state": {"values": state}},
    }


@pytest.mark.asyncio
async def test_a_sched_newvid_opens_video_modal():
    router = _sched_router()
    handler, slack = _handler(router)

    with patch("handlers.slack_interactions.vtpl.cache_is_fresh", return_value=True), \
         patch("handlers.slack_interactions.vtpl.cached_templates", return_value=_TPLS):
        resp = await handler.handle_interaction(_block_actions_payload(SCHED_NEWVID_ID))
    assert resp == {}
    await asyncio.sleep(0)

    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-vid"
    assert view["callback_id"] == SCHED_VIDEO_MODAL_ID


@pytest.mark.asyncio
async def test_b_bad_url_returns_modal_error_no_create():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _video_create_payload("not-a-url", repeat="daily", time="09:00")
    )
    await asyncio.sleep(0)

    assert resp.get("response_action") == "errors"
    assert SCHED_VID_URL_BLOCK_ID in resp.get("errors", {})
    router._tasks_client.create_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_c_happy_path_creates_video_schedule_and_confirms_dm():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _video_create_payload("https://example.com", repeat="daily", time="09:00")
    )
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.create_schedule.assert_awaited_once()
    _args, kwargs = router._tasks_client.create_schedule.call_args
    assert kwargs["kind"] == "video"
    assert kwargs["video_config"]["url"] == "https://example.com"
    assert kwargs["delivery_platform"] == "slack"
    assert kwargs["delivery_channel_id"] == "D9"
    slack.post_message.assert_awaited()
    text = slack.post_message.call_args.kwargs.get("text", "")
    assert "example.com" in text
    assert "\u2014" not in text  # no em-dash in confirmation copy


@pytest.mark.asyncio
async def test_d_template_selected_flows_into_video_config():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _video_create_payload(
            "https://example.com", repeat="daily", time="09:00",
            tpl_key="walkthrough",
        )
    )
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.create_schedule.assert_awaited_once()
    _args, kwargs = router._tasks_client.create_schedule.call_args
    assert kwargs["video_config"]["template"] == "walkthrough"
