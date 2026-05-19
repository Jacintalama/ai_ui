"""_handle_aiuibuilder — Discord-side dispatcher for /aiui aiuibuilder."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, args, captured):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c",
        raw_text=f"aiuibuilder {args}", subcommand="aiuibuilder", arguments=args,
        platform="discord", respond=respond, metadata={},
    )


def _router(mapping, tasks_client):
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock())._handle_aiuibuilder(_ctx("999", "list", captured))
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_list_empty():
    captured = []
    tc = MagicMock()
    tc.list_projects = AsyncMock(return_value=[])
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "list", captured))
    assert any("no projects" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_list_with_projects():
    captured = []
    tc = MagicMock()
    tc.list_projects = AsyncMock(return_value=[
        {"slug": "shopping", "name": "Shopping List", "role": "owner",
         "published": True, "public_url": "https://shopping.ai-ui.coolestdomain.win"},
        {"slug": "todo", "name": "Todo", "role": "editor",
         "published": False, "public_url": None},
    ])
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "list", captured))
    reply = captured[-1]
    assert "shopping" in reply and "todo" in reply
    assert "https://shopping.ai-ui.coolestdomain.win" in reply


@pytest.mark.asyncio
async def test_status_needs_slug():
    captured = []
    await _router({"100": "alice@x.com"}, MagicMock())._handle_aiuibuilder(_ctx("100", "status", captured))
    assert any("Usage" in m or "slug" in m for m in captured)


@pytest.mark.asyncio
async def test_status_404():
    captured = []
    tc = MagicMock()
    tc.get_project_status = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "status missing", captured))
    assert any("not found" in m.lower() or "yours" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_open_returns_url():
    captured = []
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "slug": "shopping", "name": "Shopping", "role": "owner",
        "published": True,
        "public_url": "https://shopping.ai-ui.coolestdomain.win",
    })
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "open shopping", captured))
    assert any("https://shopping.ai-ui.coolestdomain.win" in m for m in captured)


@pytest.mark.asyncio
async def test_open_not_published():
    captured = []
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "slug": "shopping", "name": "Shopping", "role": "owner",
        "published": False, "public_url": None,
    })
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "open shopping", captured))
    assert any("not published" in m.lower() for m in captured)
