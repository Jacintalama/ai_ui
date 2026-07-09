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
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping, tasks_client=tasks_client,
    )


def _assert_not_linked(captured):
    """New unified not-linked card: Discord ctx without respond_components falls
    back to the friendly self-service text (no person's name)."""
    assert captured, "expected a not-linked response"
    assert any("Link my account" in m for m in captured)
    assert all("Lukas" not in m for m in captured)
    assert all("isn't linked" not in m for m in captured)


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_build(_ctx("9", captured), "portfolio", "x")
    _assert_not_linked(captured)


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
    tc.start_build.assert_awaited_once_with(
        "a@x.com", "a portfolio", name="Portfolio", template_key="portfolio")
    assert any("Building" in m and "port-ab12" in m for m in captured)


@pytest.mark.asyncio
async def test_blank_build_passes_none_template():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"slug": "s", "task_id": "t1"})
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), None, "a blank app")
    tc.start_build.assert_awaited_once_with(
        "a@x.com", "a blank app", name="Blank app", template_key=None)


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

    async def fake_watch(self, ctx, email, task_id, slug, **kw):
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
    _assert_not_linked(captured)


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


@pytest.mark.asyncio
async def test_publish_service_unreachable():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(side_effect=TasksAPIError(0, "connect error"))
    await _router({"100": "a@x.com"}, tc).run_panel_publish(_ctx("100", captured), "slug-1")
    assert any("unreachable" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_enhance_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_enhance(_ctx("9", captured), "slug-1", "change")
    _assert_not_linked(captured)


@pytest.mark.asyncio
async def test_enhance_happy_path_starts_watcher(monkeypatch):
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)
    captured = []
    tc = MagicMock()
    tc.enhance_app = AsyncMock(return_value={"task_id": "t9", "slug": "slug-1", "status": "running"})
    async def notify(m): pass
    await _router({"100": "a@x.com"}, tc).run_panel_enhance(_ctx("100", captured, notify=notify), "slug-1", "make it blue")
    tc.enhance_app.assert_awaited_once_with("a@x.com", "slug-1", "make it blue")
    await asyncio.sleep(0)
    assert watched.get("args") == ("a@x.com", "t9", "slug-1")
    assert any("pdating" in m or "nhanc" in m for m in captured)


@pytest.mark.asyncio
async def test_enhance_conflict_409():
    captured = []
    tc = MagicMock(); tc.enhance_app = AsyncMock(side_effect=TasksAPIError(409, "busy"))
    await _router({"100": "a@x.com"}, tc).run_panel_enhance(_ctx("100", captured), "slug-1", "x")
    assert any("already" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_unpublish_happy_path():
    captured = []
    tc = MagicMock(); tc.unpublish_app = AsyncMock(return_value=True)
    await _router({"100": "a@x.com"}, tc).run_panel_unpublish(_ctx("100", captured), "slug-1")
    tc.unpublish_app.assert_awaited_once_with("a@x.com", "slug-1")
    assert any("offline" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_unpublish_not_owner_403():
    captured = []
    tc = MagicMock(); tc.unpublish_app = AsyncMock(side_effect=TasksAPIError(403, "no"))
    await _router({"100": "a@x.com"}, tc).run_panel_unpublish(_ctx("100", captured), "slug-1")
    assert any("owner" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_delete_happy_path():
    captured = []
    tc = MagicMock(); tc.delete_app = AsyncMock(return_value=True)
    await _router({"100": "a@x.com"}, tc).run_panel_delete(_ctx("100", captured), "slug-1")
    tc.delete_app.assert_awaited_once_with("a@x.com", "slug-1")
    assert any("delet" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_delete_not_owner_403():
    captured = []
    tc = MagicMock(); tc.delete_app = AsyncMock(side_effect=TasksAPIError(403, "no"))
    await _router({"100": "a@x.com"}, tc).run_panel_delete(_ctx("100", captured), "slug-1")
    tc.delete_app.assert_awaited_once_with("a@x.com", "slug-1")
    assert any("owner" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_delete_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_delete(_ctx("9", captured), "slug-1")
    _assert_not_linked(captured)


@pytest.mark.asyncio
async def test_publish_on_published_failure_falls_back_to_respond():
    captured = []
    tc = MagicMock()
    tc.publish_app = AsyncMock(return_value={"public_url": "https://x.example.com/"})
    async def failing_hook(url):
        raise RuntimeError("discord down")
    ctx = _ctx("100", captured)
    ctx.on_published = failing_hook
    await _router({"100": "a@x.com"}, tc).run_panel_publish(ctx, "slug-1")
    assert any("Published" in m for m in captured)
