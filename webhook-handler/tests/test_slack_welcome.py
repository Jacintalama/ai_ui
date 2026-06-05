import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.slack import SlackWebhookHandler
from handlers.app_builder_panel import PANEL_NEW_ID


def _handler():
    ow = MagicMock()
    ow.chat_completion = AsyncMock(return_value="some AI answer")
    slack = MagicMock()
    slack.post_message = AsyncMock(return_value="ts1")
    slack.format_ai_response = MagicMock(side_effect=lambda x: x)
    return SlackWebhookHandler(ow, slack), ow, slack


@pytest.mark.asyncio
async def test_dm_greeting_posts_welcome_card_not_ai():
    h, ow, slack = _handler()
    await h._handle_direct_message({"text": "hi", "channel": "D1", "user": "U1"})
    ow.chat_completion.assert_not_awaited()
    blocks = slack.post_message.call_args.kwargs["blocks"]
    action_ids = [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert PANEL_NEW_ID in action_ids


@pytest.mark.asyncio
async def test_dm_real_question_answers_with_buttons_footer():
    h, ow, slack = _handler()
    await h._handle_direct_message(
        {"text": "why is my published app returning a 404", "channel": "D1", "user": "U1"}
    )
    ow.chat_completion.assert_awaited()
    blocks = slack.post_message.call_args.kwargs["blocks"]
    assert any(b["type"] == "actions" for b in blocks)  # footer present


@pytest.mark.asyncio
async def test_mention_greeting_posts_welcome_card():
    h, ow, slack = _handler()
    await h._handle_mention({"text": "<@U999> help", "channel": "C1", "ts": "111.1", "user": "U1"})
    ow.chat_completion.assert_not_awaited()
    blocks = slack.post_message.call_args.kwargs["blocks"]
    assert any(b["type"] == "actions" for b in blocks)
