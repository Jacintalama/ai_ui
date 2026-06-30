"""Slack block-action routing for the intent-router confirm/cancel buttons.

A block_actions payload with our aiuiintent:* action_id must build a DM ctx
and run the router's run_confirmed_intent / answer_intent in the background."""
from unittest.mock import AsyncMock, MagicMock

from handlers.slack_interactions import SlackInteractionsHandler
from handlers import intent_cards


def _router():
    r = MagicMock()
    r._background_tasks = set()
    r.run_confirmed_intent = AsyncMock()
    r.answer_intent = AsyncMock()
    return r


def _handler(router):
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock()
    slack.post_ephemeral = AsyncMock()
    return SlackInteractionsHandler(slack_client=slack, command_router=router)


def _payload(action_id):
    return {"type": "block_actions",
            "actions": [{"action_id": action_id}],
            "user": {"id": "U1", "username": "x"},
            "channel": {"id": "C1"}}


async def test_slack_intent_confirm_runs_router():
    r = _router()
    h = _handler(r)
    resp = await h._handle_block_actions(_payload(intent_cards.INTENT_CONFIRM_PREFIX + "tok"))
    assert resp == {}  # immediate ACK
    for t in list(r._background_tasks):
        await t
    r.run_confirmed_intent.assert_awaited_once()


async def test_slack_intent_cancel_runs_answer():
    r = _router()
    h = _handler(r)
    await h._handle_block_actions(_payload(intent_cards.INTENT_CANCEL_PREFIX + "tok"))
    for t in list(r._background_tasks):
        await t
    r.answer_intent.assert_awaited_once()
