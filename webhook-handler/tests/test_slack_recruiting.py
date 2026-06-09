import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.slack_interactions import SlackInteractionsHandler
from handlers import slack_recruiting_panel as srp


def _handler(router):
    slack = MagicMock(); slack.open_modal = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value=True)
    slack.open_dm = AsyncMock(return_value="D1")
    return SlackInteractionsHandler(slack_client=slack, command_router=router)


@pytest.mark.asyncio
async def test_find_button_opens_modal():
    h = _handler(MagicMock())
    payload = {"type": "block_actions", "trigger_id": "tg",
               "channel": {"id": "c"}, "user": {"id": "u"},
               "actions": [{"action_id": srp.OUT_FIND_ACTION_ID}]}
    await h.handle_interaction(payload)
    h.slack.open_modal.assert_awaited_once()


@pytest.mark.asyncio
async def test_view_submission_dispatches():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count): calls.append((role, count))
    router.run_panel_outreach = fake
    # the handler may resolve email via router; make it linked
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    h = _handler(router)
    view = {"callback_id": srp.OUT_MODAL_CALLBACK,
            "private_metadata": "c",
            "state": {"values": srp.sample_state("Python", "Berlin", "Hiring", "8")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    await h.handle_interaction(payload)
    for _ in range(6):
        await asyncio.sleep(0)
    assert calls and calls[0] == ("Python", 8)
