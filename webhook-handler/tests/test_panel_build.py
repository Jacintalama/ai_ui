"""CommandRouter.run_panel_build — App Builder channel build entry."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, captured, *, notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="t", channel_id="c",
        raw_text="", subcommand="aiuibuilder", arguments="",
        platform="discord", respond=respond, metadata={},
        notify_channel=notify,
    )


def _router(mapping, tasks_client):
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping, tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_build(_ctx("9", captured), "portfolio", "x")
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_empty_description_rejected():
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), "portfolio", "   ")
    assert any("describe" in m.lower() for m in captured)
    tc.start_build.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_starts_build():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"slug": "port-ab12", "task_id": "t1"})
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), "portfolio", "a portfolio")
    tc.start_build.assert_awaited_once_with("a@x.com", "a portfolio", template_key="portfolio")
    assert any("Building `port-ab12`" in m for m in captured)


@pytest.mark.asyncio
async def test_blank_build_passes_none_template():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"slug": "s", "task_id": "t1"})
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), None, "a blank app")
    tc.start_build.assert_awaited_once_with("a@x.com", "a blank app", template_key=None)


@pytest.mark.asyncio
async def test_build_error_surfaced():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(side_effect=TasksAPIError(429, "busy"))
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), "portfolio", "x")
    assert any("already running" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_watcher_wired_when_notify_channel_set(monkeypatch):
    watched = {}

    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)

    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)

    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"slug": "s", "task_id": "t1"})

    async def notify(msg):
        pass

    await _router({"100": "a@x.com"}, tc).run_panel_build(
        _ctx("100", captured, notify=notify), "portfolio", "a portfolio"
    )
    await asyncio.sleep(0)
    assert watched.get("args") == ("a@x.com", "t1", "s")


@pytest.mark.asyncio
async def test_publish_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_publish(_ctx("9", captured), "slug-1")
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_publish_happy_path():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(return_value={
        "published": True, "public_url": "https://slug-1.ai-ui.coolestdomain.win/"})
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    tc.publish_app.assert_awaited_once_with("a@x.com", "slug-1")
    assert any("Published" in m and "https://slug-1.ai-ui.coolestdomain.win/" in m for m in captured)


@pytest.mark.asyncio
async def test_publish_non_owner_403():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(side_effect=TasksAPIError(403, "denied"))
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    assert any("owner" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_publish_no_index_400():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(side_effect=TasksAPIError(400, "no index"))
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    assert any("index.html" in m.lower() or "publishable" in m.lower() for m in captured)
