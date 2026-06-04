"""SlackWebhookHandler event routing: the conversational DM handler must NOT
respond to its own message edits/echoes.

Regression: posting the schedules panel and then editing it in place (via
response_url replace_original) fires `message_changed` events in the DM. Those
have no top-level `user`/`text`/`bot_id` (they're nested under `event.message`),
so the old handler logged "Slack DM from unknown:" and asked Open WebUI to reply
to an empty string -> the bot spammed "your message came through blank".
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.slack import SlackWebhookHandler


def _handler():
    openwebui = MagicMock()
    openwebui.chat_completion = AsyncMock(return_value="hello!")
    slack = MagicMock()
    slack.post_message = AsyncMock(return_value="ts")
    slack.format_ai_response = MagicMock(side_effect=lambda x: x)
    return SlackWebhookHandler(
        openwebui_client=openwebui, slack_client=slack,
        ai_model="m", ai_system_prompt="sys",
    ), openwebui, slack


def _dm_payload(event: dict) -> dict:
    return {"type": "event_callback", "event": {
        "type": "message", "channel_type": "im", "channel": "D1", **event}}


@pytest.mark.asyncio
async def test_message_changed_edit_is_ignored():
    """A message_changed event (our own in-place panel edit) must not trigger
    an AI reply."""
    handler, openwebui, slack = _handler()
    payload = _dm_payload({
        "subtype": "message_changed",
        "message": {"text": "Your schedules", "user": "Ubot"},
        "previous_message": {"text": "Your schedules", "user": "Ubot"},
    })
    await handler.handle_event(payload)
    openwebui.chat_completion.assert_not_awaited()
    slack.post_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_deleted_is_ignored():
    handler, openwebui, slack = _handler()
    await handler.handle_event(_dm_payload({"subtype": "message_deleted"}))
    openwebui.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_message_subtype_is_ignored():
    handler, openwebui, slack = _handler()
    await handler.handle_event(_dm_payload(
        {"subtype": "bot_message", "text": "a quote", "bot_id": "B1"}))
    openwebui.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_text_dm_is_ignored():
    """Even a genuinely blank user message must not reach the AI."""
    handler, openwebui, slack = _handler()
    await handler.handle_event(_dm_payload({"text": "   ", "user": "U1"}))
    openwebui.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_user_dm_still_replies():
    """A normal user DM with text must still get an AI reply (no over-filtering)."""
    handler, openwebui, slack = _handler()
    await handler.handle_event(_dm_payload({"text": "hello there", "user": "U1"}))
    openwebui.chat_completion.assert_awaited_once()
    slack.post_message.assert_awaited_once()
