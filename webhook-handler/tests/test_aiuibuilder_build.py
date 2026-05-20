"""_handle_aiuibuilder `build` action."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, args, captured, notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c1",
        raw_text=f"aiuibuilder {args}", subcommand="aiuibuilder", arguments=args,
        platform="discord", respond=respond, metadata={}, notify_channel=notify,
    )


def _router(mapping, tasks_client):
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_build_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock())._handle_aiuibuilder(_ctx("999", 'build "x"', captured))
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_build_missing_description_shows_usage():
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "build", captured))
    assert any("Usage" in m for m in captured)
    tc.start_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_happy_path_starts_and_acks(monkeypatch):
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "todo-a1b2", "status": "running"})
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)

    async def notify(msg):
        pass
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", 'build "a todo list with dark mode"', captured, notify=notify)
    )
    await asyncio.sleep(0)
    tc.start_build.assert_awaited_once()
    assert tc.start_build.call_args.args[1] == "a todo list with dark mode"
    assert any("Building" in m and "todo-a1b2" in m for m in captured)
    assert watched["args"] == ("a@x.com", "t1", "todo-a1b2")


@pytest.mark.asyncio
async def test_build_unquoted_description_works():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build a todo list", captured, notify=None)
    )
    assert tc.start_build.call_args.args[1] == "a todo list"


@pytest.mark.asyncio
async def test_build_429_says_already_running():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(side_effect=TasksAPIError(429, "A build is already running"))
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", 'build "x"', captured, notify=None)
    )
    assert any("already running" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_existing_list_still_works():
    captured = []
    tc = MagicMock(); tc.list_projects = AsyncMock(return_value=[])
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "list", captured))
    assert any("no projects" in m.lower() for m in captured)
