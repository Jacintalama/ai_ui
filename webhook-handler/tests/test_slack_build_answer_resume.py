"""Slack: a DM reply to a paused build's question resumes it (mirrors the
Discord app-thread flow, reusing the shared try_resume_paused_build)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.slack import SlackWebhookHandler


def _handler(router):
    h = SlackWebhookHandler(openwebui_client=MagicMock(), slack_client=MagicMock())
    h.slack.post_message = AsyncMock()
    h.router = router
    return h


@pytest.mark.asyncio
async def test_dm_reply_resumes_paused_build():
    router = MagicMock()
    router.try_resume_paused_build = AsyncMock(return_value=True)
    h = _handler(router)
    event = {"type": "message", "channel_type": "im",
             "user": "U1", "channel": "D1", "text": "use dark teal"}
    result = await h._handle_direct_message(event)
    router.try_resume_paused_build.assert_awaited_once()
    args = router.try_resume_paused_build.call_args.args
    assert args[1] == "U1"          # uid
    assert args[2] == "use dark teal"  # answer text
    assert result.get("message") == "Build answer resumed"


@pytest.mark.asyncio
async def test_dm_without_paused_build_falls_through():
    router = MagicMock()
    router.try_resume_paused_build = AsyncMock(return_value=False)
    h = _handler(router)
    h._try_intent = AsyncMock(return_value=True)  # short-circuit before any AI call
    event = {"type": "message", "channel_type": "im",
             "user": "U1", "channel": "D1", "text": "abcxyz status"}
    result = await h._handle_direct_message(event)
    router.try_resume_paused_build.assert_awaited_once()
    assert result.get("message") != "Build answer resumed"
