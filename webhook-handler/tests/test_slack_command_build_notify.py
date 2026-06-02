"""Slack slash handler wires notify_channel so builds post the link to channel."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.slack_commands import SlackCommandHandler


def _handler(router=None):
    slack = MagicMock()
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_to_response_url = AsyncMock(return_value=True)
    router = router or MagicMock()
    router.execute = AsyncMock(return_value=None)
    return SlackCommandHandler(slack_client=slack, command_router=router), slack, router


@pytest.mark.asyncio
async def test_command_sets_notify_channel_that_posts_to_channel():
    handler, slack, router = _handler()
    form = {
        "command": "/aiui",
        "text": 'aiuibuilder build "a todo app"',
        "response_url": "https://hooks.slack.com/x",
        "user_id": "U1",
        "user_name": "maya",
        "channel_id": "C-build",
        "team_id": "T1",
    }
    await handler.handle_command(form)
    await asyncio.sleep(0)  # let the fire-and-forget execute task run
    router.execute.assert_awaited_once()
    ctx = router.execute.call_args.args[0]
    assert ctx.platform == "slack"
    assert ctx.notify_channel is not None
    await ctx.notify_channel("`slug` is ready: http://x")
    slack.post_message.assert_awaited_with(channel="C-build", text="`slug` is ready: http://x")


@pytest.mark.asyncio
async def test_no_channel_means_no_notifier():
    handler, slack, router = _handler()
    form = {"command": "/aiui", "text": "status", "user_id": "U1", "channel_id": ""}
    await handler.handle_command(form)
    await asyncio.sleep(0)
    ctx = router.execute.call_args.args[0]
    assert ctx.notify_channel is None


@pytest.mark.asyncio
async def test_immediate_ack_returned():
    handler, slack, router = _handler()
    form = {"command": "/aiui", "text": "status", "user_id": "U1", "channel_id": "C1"}
    result = await handler.handle_command(form)
    assert result["response_type"] == "ephemeral"
    assert "Processing" in result["text"]
