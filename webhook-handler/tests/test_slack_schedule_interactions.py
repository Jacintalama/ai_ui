"""SlackInteractionsHandler: cron-scheduler panel button clicks + modal submits.

Mirrors the App Builder interaction tests (test_slack_interactions.py): Mock
slack + router._tasks_client, AsyncMocks, router._background_tasks = set().
"""
import asyncio
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


def _block_actions_payload(action_id: str, user_id: str = "U1") -> dict:
    return {
        "type": "block_actions",
        "trigger_id": "trig-sched",
        "user": {"id": user_id, "username": "tester"},
        "channel": {"id": "C-panel"},
        "team": {"id": "T1"},
        "actions": [{"action_id": action_id}],
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

    router._tasks_client.list_schedules.assert_awaited_once_with("u@x.com")
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
    router = _sched_router()
    handler, slack = _handler(router)

    resp = await handler.handle_interaction(
        _block_actions_payload(f"{SCHED_EDIT_PREFIX}7")
    )
    assert resp == {}
    await asyncio.sleep(0)

    slack.open_modal.assert_awaited_once()
    trigger, view = slack.open_modal.call_args.args
    assert view["callback_id"] == f"{SCHED_EDITMODAL_PREFIX}7"


@pytest.mark.asyncio
async def test_create_submission_parseable_creates_schedule():
    router = _sched_router()
    handler, slack = _handler(router)

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
    assert resp == {}  # empty 200 closes the modal
    await asyncio.sleep(0)

    router._tasks_client.create_schedule.assert_awaited_once()
    _args, kwargs = router._tasks_client.create_schedule.call_args
    assert kwargs["cron"] == "0 8 * * *"
    assert kwargs["prompt"] == "summarize my unread emails and list the top 3"
    assert kwargs["delivery_platform"] == "slack"
    assert kwargs["delivery_channel_id"] == "D9"
    # confirmation DM'd
    slack.post_message.assert_awaited()


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
