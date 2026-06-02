"""CommandRouter._resolve_email_for_ctx: Slack uses the API, Discord uses the map."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext


def _ctx(platform, user_id, args, captured, notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="C1",
        raw_text=f"aiuibuilder {args}", subcommand="aiuibuilder", arguments=args,
        platform=platform, respond=respond, metadata={}, notify_channel=notify,
    )


def _router(*, slack_client=None, mapping=None, tasks_client=None):
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        slack_client=slack_client,
        discord_user_email_map=mapping or {},
        tasks_client=tasks_client or MagicMock(),
    )


@pytest.mark.asyncio
async def test_resolve_email_slack_uses_api():
    slack = MagicMock()
    slack.get_user_email = AsyncMock(return_value="alice@x.com")
    r = _router(slack_client=slack, mapping={})
    ctx = _ctx("slack", "U123", "list", [])
    assert await r._resolve_email_for_ctx(ctx) == "alice@x.com"
    slack.get_user_email.assert_awaited_once_with("U123")


@pytest.mark.asyncio
async def test_resolve_email_discord_uses_map():
    slack = MagicMock()
    slack.get_user_email = AsyncMock(return_value="should-not-be-used@x.com")
    r = _router(slack_client=slack, mapping={"100": "bob@x.com"})
    ctx = _ctx("discord", "100", "list", [])
    assert await r._resolve_email_for_ctx(ctx) == "bob@x.com"
    slack.get_user_email.assert_not_awaited()  # Discord never hits the Slack API


@pytest.mark.asyncio
async def test_resolve_email_slack_no_client_returns_none():
    r = _router(slack_client=None, mapping={})
    assert await r._resolve_email_for_ctx(_ctx("slack", "U123", "list", [])) is None


@pytest.mark.asyncio
async def test_slack_unresolvable_user_gets_scope_hint():
    slack = MagicMock()
    slack.get_user_email = AsyncMock(return_value=None)
    captured = []
    r = _router(slack_client=slack, mapping={})
    await r._handle_aiuibuilder(_ctx("slack", "U999", 'build "x"', captured))
    assert any("users:read.email" in m for m in captured)
    assert all("isn't linked" not in m for m in captured)  # not the Discord copy


@pytest.mark.asyncio
async def test_slack_build_resolves_email_and_starts(monkeypatch):
    slack = MagicMock()
    slack.get_user_email = AsyncMock(return_value="maya@x.com")
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[])
    tc.start_build = AsyncMock(
        return_value={"task_id": "t1", "slug": "todo-1", "status": "running"}
    )
    monkeypatch.setattr(
        CommandRouter, "_watch_build",
        AsyncMock(return_value=None),
    )
    captured = []

    async def notify(msg):
        pass

    r = _router(slack_client=slack, mapping={}, tasks_client=tc)
    await r._handle_aiuibuilder(_ctx("slack", "U1", 'build "a todo app"', captured, notify=notify))
    await asyncio.sleep(0)
    tc.start_build.assert_awaited_once()
    assert tc.start_build.call_args.args[0] == "maya@x.com"  # build owned by resolved email
    assert tc.start_build.call_args.args[1] == "a todo app"
    assert any("Building" in m for m in captured)
