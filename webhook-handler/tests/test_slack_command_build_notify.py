"""Slack slash handler wires notify_channel so builds post the link to channel."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from handlers.slack_commands import SlackCommandHandler
from handlers.commands import CommandRouter


def _handler(router=None):
    slack = MagicMock()
    slack.post_message = AsyncMock(return_value="ts")
    slack.post_to_response_url = AsyncMock(return_value=True)
    router = router or MagicMock()
    router.execute = AsyncMock(return_value=None)
    return SlackCommandHandler(slack_client=slack, command_router=router), slack, router


def _list_router() -> MagicMock:
    """Build a router mock with the collaborators needed for the list path."""
    router = MagicMock()
    router.execute = AsyncMock(return_value=None)
    router.parse_command = CommandRouter.parse_command  # real staticmethod
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_projects = AsyncMock(
        return_value=[{"slug": "app1", "published": True}]
    )
    router._not_linked_text = MagicMock(return_value="not linked")
    return router


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


# ---------------------------------------------------------------------------
# E13 — /aiui aiuibuilder list renders interactive Block Kit app list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aiuibuilder_list_renders_blocks():
    """list path: resolves email, fetches projects, posts blocks via response_url."""
    router = _list_router()
    handler, slack, _ = _handler(router=router)
    form = {
        "command": "/aiui",
        "text": "aiuibuilder list",
        "user_id": "U1",
        "user_name": "maya",
        "channel_id": "C1",
        "response_url": "https://hooks/x",
        "team_id": "T1",
    }
    result = await handler.handle_command(form)
    # Immediate ACK must be ephemeral
    assert result["response_type"] == "ephemeral"
    # Give the background task a chance to run
    await asyncio.sleep(0)
    # list_projects was called with the resolved email
    router._tasks_client.list_projects.assert_awaited_once_with("u@x.com")
    # post_to_response_url was called with blocks= kwarg (Block Kit list)
    slack.post_to_response_url.assert_awaited_once()
    kwargs = slack.post_to_response_url.call_args.kwargs
    assert "blocks" in kwargs, "Expected blocks= kwarg in post_to_response_url call"
    assert isinstance(kwargs["blocks"], list) and len(kwargs["blocks"]) > 0
    # router.execute must NOT have been called (list is handled by the new path)
    router.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_aiuibuilder_list_email_none_posts_not_linked():
    """list path: when email resolution fails, post not-linked text without blocks."""
    router = _list_router()
    router._resolve_email_for_ctx = AsyncMock(return_value=None)
    handler, slack, _ = _handler(router=router)
    form = {
        "command": "/aiui",
        "text": "aiuibuilder list",
        "user_id": "U1",
        "user_name": "maya",
        "channel_id": "C1",
        "response_url": "https://hooks/x",
        "team_id": "T1",
    }
    await handler.handle_command(form)
    await asyncio.sleep(0)
    # list_projects must NOT have been called
    router._tasks_client.list_projects.assert_not_awaited()
    # post_to_response_url called with the not-linked text, no blocks
    slack.post_to_response_url.assert_awaited_once()
    kwargs = slack.post_to_response_url.call_args.kwargs
    assert "blocks" not in kwargs or kwargs.get("blocks") is None


@pytest.mark.asyncio
async def test_other_subcommand_still_uses_router_execute():
    """Non-list subcommands must flow through the existing router.execute path."""
    router = _list_router()
    handler, slack, _ = _handler(router=router)
    form = {
        "command": "/aiui",
        "text": "status",
        "user_id": "U1",
        "user_name": "maya",
        "channel_id": "C1",
        "response_url": "https://hooks/x",
        "team_id": "T1",
    }
    await handler.handle_command(form)
    await asyncio.sleep(0)
    # existing path: router.execute IS called
    router.execute.assert_awaited_once()
    # list_projects must NOT have been called (this is not the list path)
    router._tasks_client.list_projects.assert_not_awaited()
