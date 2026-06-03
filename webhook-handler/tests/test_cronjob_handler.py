"""_handle_cronjob — Discord-side dispatcher for /aiui cronjob.

Covers:
  - unmapped Discord user → friendly reject
  - empty/unknown action → usage hint
  - list with no schedules → "no schedules" message
  - list with schedules → formatted reply
  - create with missing args → usage hint
  - create with bad cron → propagates tasks 400
  - create success → reply with new id
  - delete 404 → "no such schedule"
  - tasks unreachable → "tasks service unreachable"
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, args, captured):
    """Build a CommandContext that captures the reply."""
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c",
        raw_text=f"cronjob {args}", subcommand="cronjob", arguments=args,
        platform="discord", respond=respond, metadata={},
    )


def _router(mapping, tasks_client):
    """Build a CommandRouter with mocked deps via the new ctor kwargs."""
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    router = _router({}, MagicMock())
    await router._handle_cronjob(_ctx("999", "list", captured))
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_list_empty():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[])
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "list", captured))
    assert any("no schedules" in m.lower() for m in captured)
    tc.list_schedules.assert_called_once_with("alice@x.com", platform="discord")


@pytest.mark.asyncio
async def test_list_with_schedules():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "s1", "name": "morning", "cron_expr": "0 8 * * *", "enabled": True},
        {"id": "s2", "name": "hourly", "cron_expr": "0 * * * *", "enabled": False},
    ])
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "list", captured))
    reply = captured[-1]
    assert "s1" in reply and "morning" in reply
    assert "s2" in reply and "hourly" in reply


@pytest.mark.asyncio
async def test_create_missing_args_usage_hint():
    captured = []
    tc = MagicMock()
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "create", captured))
    assert any("Need" in m or "Usage" in m for m in captured)


@pytest.mark.asyncio
async def test_create_success():
    captured = []
    tc = MagicMock()
    tc.create_schedule = AsyncMock(return_value={"id": "new-uuid"})
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", 'create "0 8 * * *" "summarize emails"', captured))
    tc.create_schedule.assert_called_once()
    args = tc.create_schedule.call_args
    assert args.args[0] == "alice@x.com"  # user_email
    assert args.kwargs["cron"] == "0 8 * * *"
    assert args.kwargs["prompt"] == "summarize emails"


@pytest.mark.asyncio
async def test_create_invalid_cron_propagates():
    captured = []
    tc = MagicMock()
    tc.create_schedule = AsyncMock(side_effect=TasksAPIError(400, "invalid cron_expr"))
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", 'create "bad" "prompt"', captured))
    assert any("Invalid cron" in m for m in captured)


@pytest.mark.asyncio
async def test_delete_404():
    captured = []
    tc = MagicMock()
    tc.delete_schedule = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "delete missing-id", captured))
    assert any("No such schedule" in m for m in captured)


@pytest.mark.asyncio
async def test_tasks_unreachable():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(side_effect=TasksAPIError(0, "refused"))
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "list", captured))
    assert any("unreachable" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_unknown_action_usage():
    captured = []
    tc = MagicMock()
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "frobnicate", captured))
    assert any("Usage" in m for m in captured)
