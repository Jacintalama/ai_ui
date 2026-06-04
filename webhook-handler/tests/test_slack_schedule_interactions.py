"""SlackInteractionsHandler: cron-scheduler panel button clicks + modal submits.

Mirrors the App Builder interaction tests (test_slack_interactions.py): Mock
slack + router._tasks_client, AsyncMocks, router._background_tasks = set().
"""
import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.slack_interactions import SlackInteractionsHandler
from handlers.app_builder_panel import (
    SCHED_OPEN_ID,
    SCHED_NEW_ID,
    SCHED_MODAL_ID,
    SCHED_EDITMODAL_PREFIX,
    SCHED_RUN_PREFIX,
    SCHED_DEL_PREFIX,
    SCHED_EDIT_PREFIX,
    CONNECT_RESUME_PREFIX,
)
from handlers.slack_schedule_panel import (
    SCHED_WHAT_BLOCK_ID,
    SCHED_WHAT_INPUT_ID,
    SCHED_WHEN_BLOCK_ID,
    SCHED_WHEN_INPUT_ID,
)


def _handler(router, slack=None):
    slack = slack or MagicMock()
    slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D9")
    return SlackInteractionsHandler(slack_client=slack, command_router=router), slack


def _sched_router():
    """Router mock wired for schedule action tests."""
    router = MagicMock()
    router._background_tasks = set()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._not_linked_text = MagicMock(return_value="not-linked msg")
    router._tasks_client = MagicMock()
    router._tasks_client.list_schedules = AsyncMock(return_value=[
        {"id": 7, "prompt": "summarize my unread emails", "cron_expr": "0 9 * * *",
         "enabled": True},
    ])
    router._tasks_client.create_schedule = AsyncMock(return_value={"id": 11})
    router._tasks_client.update_schedule = AsyncMock(return_value={"id": 7})
    router._tasks_client.run_schedule_now = AsyncMock(return_value=True)
    router._tasks_client.pause_schedule = AsyncMock(return_value=True)
    router._tasks_client.resume_schedule = AsyncMock(return_value=True)
    router._tasks_client.delete_schedule = AsyncMock(return_value=True)
    return router


def _block_actions_payload(action_id: str, user_id: str = "U1",
                           value: str = None) -> dict:
    action = {"action_id": action_id}
    if value is not None:
        action["value"] = value
    return {
        "type": "block_actions",
        "trigger_id": "trig-sched",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": "C-panel"},
        "team": {"id": "T1"},
        "actions": [action],
    }


def _view_submission_payload(callback_id: str, what: str, when: str,
                             user_id: str = "U1") -> dict:
    return {
        "type": "view_submission",
        "user": {"id": user_id, "username": "tester"},
        "view": {
            "callback_id": callback_id,
            "state": {"values": {
                SCHED_WHAT_BLOCK_ID: {SCHED_WHAT_INPUT_ID: {"value": what}},
                SCHED_WHEN_BLOCK_ID: {SCHED_WHEN_INPUT_ID: {"value": when}},
            }},
        },
    }


@pytest.mark.asyncio
async def test_sched_open_posts_dashboard_to_dm():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(_block_actions_payload(SCHED_OPEN_ID))
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.list_schedules.assert_awaited_once_with(
        "u@x.com", platform="slack")
    slack.open_dm.assert_awaited()
    # dashboard posted to the DM channel
    slack.post_message.assert_awaited()
    kwargs = slack.post_message.call_args.kwargs
    assert kwargs["channel"] == "D9"
    assert isinstance(kwargs["blocks"], list) and kwargs["blocks"]


@pytest.mark.asyncio
async def test_sched_new_opens_create_modal():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(_block_actions_payload(SCHED_NEW_ID))
    assert resp == {}
    await asyncio.sleep(0)

    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-sched"
    assert view["callback_id"] == SCHED_MODAL_ID


@pytest.mark.asyncio
async def test_sched_run_prefix_calls_run_now():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _block_actions_payload(f"{SCHED_RUN_PREFIX}7")
    )
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.run_schedule_now.assert_awaited_once_with("u@x.com", "7")
    # the re-render after the action also scopes to slack schedules only
    router._tasks_client.list_schedules.assert_awaited_with(
        "u@x.com", platform="slack")


@pytest.mark.asyncio
async def test_sched_action_updates_panel_in_place_via_response_url():
    """When the action click carries a response_url (it was clicked inside an
    existing panel), the refreshed dashboard REPLACES that panel in place
    instead of posting a brand-new one (no more stacked duplicates)."""
    router = _sched_router()
    handler, slack = _handler(router)
    slack.post_to_response_url = AsyncMock(return_value=True)

    payload = _block_actions_payload(f"{SCHED_RUN_PREFIX}7")
    payload["response_url"] = "https://hooks.slack.test/resp-abc"
    resp = await handler.handle_interaction(payload)
    assert resp == {}
    await asyncio.sleep(0)

    slack.post_to_response_url.assert_awaited_once()
    args, kwargs = slack.post_to_response_url.call_args
    assert args[0] == "https://hooks.slack.test/resp-abc"
    assert kwargs.get("replace_original") is True
    assert kwargs.get("blocks")
    # NOT a fresh DM post — that was the duplicate-stacking bug
    slack.post_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_sched_action_without_response_url_falls_back_to_dm_post():
    """No response_url (e.g. legacy panel) → keep the old behavior: post the
    refreshed dashboard to the DM."""
    router = _sched_router()
    handler, slack = _handler(router)
    slack.post_to_response_url = AsyncMock(return_value=True)

    # _block_actions_payload sets no response_url
    resp = await handler.handle_interaction(
        _block_actions_payload(f"{SCHED_RUN_PREFIX}7")
    )
    assert resp == {}
    await asyncio.sleep(0)

    slack.post_to_response_url.assert_not_awaited()
    slack.post_message.assert_awaited()


@pytest.mark.asyncio
async def test_sched_del_prefix_calls_delete():
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _block_actions_payload(f"{SCHED_DEL_PREFIX}7")
    )
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.delete_schedule.assert_awaited_once_with("u@x.com", "7")


@pytest.mark.asyncio
async def test_sched_edit_prefix_opens_edit_modal():
    """Edit-open is synchronous: the prefill rides in the button `value`, so the
    modal opens with NO preceding network I/O (avoids trigger_id expiry)."""
    router = _sched_router()
    handler, slack = _handler(router)

    value = json.dumps(
        {"id": "7", "prompt": "summarize my unread emails", "cron": "0 9 * * *"}
    )
    resp = await handler.handle_interaction(
        _block_actions_payload(f"{SCHED_EDIT_PREFIX}7", value=value)
    )
    assert resp == {}
    await asyncio.sleep(0)

    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert trigger == "trig-sched"
    assert view["callback_id"] == f"{SCHED_EDITMODAL_PREFIX}7"
    # prefill came from the button value, not a fetch
    inputs = [
        b for b in view["blocks"]
        if b.get("element", {}).get("type") == "plain_text_input"
    ]
    initials = {b["element"].get("initial_value") for b in inputs}
    assert "summarize my unread emails" in initials
    # When is prefilled in plain English (matches Discord), not raw cron.
    assert "every day at 9:00 AM" in initials
    # no schedule fetch for the edit-open path
    router._tasks_client.list_schedules.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_submission_parseable_creates_schedule():
    router = _sched_router()
    handler, slack = _handler(router)

    # "emails" triggers the Gmail connector gate; simulate already-connected so
    # the create path runs (the gate itself is covered by its own tests).
    with patch(
        "handlers.slack_interactions.parse_when",
        return_value=("0 8 * * *", "every day at 8:00 AM"),
    ), patch(
        "handlers.slack_interactions.connectors.is_connected",
        new=AsyncMock(return_value=True),
    ):
        resp = await handler.handle_interaction(
            _view_submission_payload(
                SCHED_MODAL_ID,
                what="summarize my unread emails and list the top 3",
                when="every morning at 8am",
            )
        )
        # Drain the background task WHILE the patch is still active.
        await asyncio.sleep(0)
    assert resp == {}  # empty 200 closes the modal

    router._tasks_client.create_schedule.assert_awaited_once()
    _args, kwargs = router._tasks_client.create_schedule.call_args
    assert kwargs["cron"] == "0 8 * * *"
    assert kwargs["prompt"] == "summarize my unread emails and list the top 3"
    assert kwargs["delivery_platform"] == "slack"
    assert kwargs["delivery_channel_id"] == "D9"
    # confirmation DM'd
    slack.post_message.assert_awaited()


@pytest.mark.asyncio
async def test_create_submission_without_dm_does_not_create_schedule():
    router = _sched_router()
    handler, slack = _handler(router)
    slack.open_dm.return_value = None

    with patch(
        "handlers.slack_interactions.parse_when",
        return_value=("0 8 * * *", "every day at 8:00 AM"),
    ):
        resp = await handler.handle_interaction(
            _view_submission_payload(
                SCHED_MODAL_ID,
                what="summarize my unread emails and list the top 3",
                when="every morning at 8am",
            )
        )
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.create_schedule.assert_not_awaited()
    slack.post_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_submission_unparseable_returns_errors_and_no_create():
    router = _sched_router()
    handler, slack = _handler(router)

    with patch("handlers.slack_interactions.parse_when", return_value=None):
        resp = await handler.handle_interaction(
            _view_submission_payload(
                SCHED_MODAL_ID,
                what="do a thing",
                when="gibberish nonsense",
            )
        )
    await asyncio.sleep(0)

    assert resp.get("response_action") == "errors"
    assert SCHED_WHEN_BLOCK_ID in resp.get("errors", {})
    router._tasks_client.create_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_submission_parseable_calls_update():
    router = _sched_router()
    handler, slack = _handler(router)

    with patch(
        "handlers.slack_interactions.parse_when",
        return_value=("0 7 * * 1", "every Monday at 7:00 AM"),
    ):
        resp = await handler.handle_interaction(
            _view_submission_payload(
                f"{SCHED_EDITMODAL_PREFIX}7",
                what="updated prompt text",
                when="every monday 7am",
            )
        )
    assert resp == {}
    await asyncio.sleep(0)

    router._tasks_client.update_schedule.assert_awaited_once()
    args, kwargs = router._tasks_client.update_schedule.call_args
    # positional: (email, schedule_id)
    assert args[0] == "u@x.com"
    assert args[1] == "7"
    assert kwargs["cron"] == "0 7 * * 1"
    assert kwargs["prompt"] == "updated prompt text"


# --- Connector gate (Gmail/Drive) on schedule create ---

def _resume_pending(handler, token="tok9"):
    handler._pending_schedules[token] = {
        "name": "n", "cron": "0 8 * * *", "prompt": "email me a quote",
        "human": "every day at 8:00 AM", "dm": "D9",
    }


@pytest.mark.asyncio
async def test_create_unconnected_connector_shows_connect_card_no_create():
    router = _sched_router()
    handler, slack = _handler(router)
    with patch(
        "handlers.slack_interactions.parse_when",
        return_value=("0 8 * * *", "every day at 8:00 AM"),
    ), patch(
        "handlers.slack_interactions.connectors.is_connected",
        new=AsyncMock(return_value=False),
    ):
        resp = await handler.handle_interaction(
            _view_submission_payload(
                SCHED_MODAL_ID,
                what="send a quote to my email rambo@x.com",
                when="every morning at 8am",
            )
        )
        await asyncio.sleep(0)  # drain while patch is active
    assert resp == {}
    # Parked behind the gate, not created.
    router._tasks_client.create_schedule.assert_not_awaited()
    blocks = slack.post_message.call_args.kwargs.get("blocks") or []
    ids = [el.get("action_id") for b in blocks if b.get("type") == "actions"
           for el in b.get("elements", [])]
    assert any(i and i.startswith(CONNECT_RESUME_PREFIX) for i in ids)
    assert len(handler._pending_schedules) == 1


@pytest.mark.asyncio
async def test_create_no_connector_intent_creates_without_checking():
    router = _sched_router()
    handler, slack = _handler(router)
    checked = {"hit": False}

    async def _fake_is_connected(*a, **k):
        checked["hit"] = True
        return False

    with patch(
        "handlers.slack_interactions.parse_when",
        return_value=("0 8 * * *", "every day at 8:00 AM"),
    ), patch(
        "handlers.slack_interactions.connectors.is_connected",
        new=_fake_is_connected,
    ):
        await handler.handle_interaction(
            _view_submission_payload(
                SCHED_MODAL_ID, what="give me a motivational quote",
                when="every morning at 8am",
            )
        )
    await asyncio.sleep(0)
    router._tasks_client.create_schedule.assert_awaited_once()
    assert checked["hit"] is False  # no Gmail/Drive intent -> no connection check
    assert handler._pending_schedules == {}


@pytest.mark.asyncio
async def test_connect_resume_creates_when_connected():
    router = _sched_router()
    handler, slack = _handler(router)
    slack.post_to_response_url = AsyncMock(return_value=True)
    _resume_pending(handler)
    payload = _block_actions_payload(f"{CONNECT_RESUME_PREFIX}tok9")
    payload["response_url"] = "https://hooks.slack.test/resume"
    with patch(
        "handlers.slack_interactions.connectors.is_connected",
        new=AsyncMock(return_value=True),
    ):
        resp = await handler.handle_interaction(payload)
        await asyncio.sleep(0)  # drain while patch is active
    assert resp == {}
    router._tasks_client.create_schedule.assert_awaited_once()
    assert "tok9" not in handler._pending_schedules
    assert "Scheduled" in slack.post_to_response_url.call_args.args[1]


@pytest.mark.asyncio
async def test_connect_resume_still_missing_keeps_parked_no_create():
    router = _sched_router()
    handler, slack = _handler(router)
    slack.post_to_response_url = AsyncMock(return_value=True)
    _resume_pending(handler)
    payload = _block_actions_payload(f"{CONNECT_RESUME_PREFIX}tok9")
    payload["response_url"] = "https://hooks.slack.test/resume"
    with patch(
        "handlers.slack_interactions.connectors.is_connected",
        new=AsyncMock(return_value=False),
    ):
        await handler.handle_interaction(payload)
        await asyncio.sleep(0)  # drain while patch is active
    router._tasks_client.create_schedule.assert_not_awaited()
    assert "tok9" in handler._pending_schedules
    assert "Still not connected" in slack.post_to_response_url.call_args.args[1]
