"""_handle_aiuibuilder `build` action."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import (
    CommandRouter, CommandContext, BUILD_MAX_CONSECUTIVE_ERRORS,
)
from clients.tasks import TasksAPIError


async def _noop():
    return None


def _ctx(user_id, args, captured, notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c1",
        raw_text=f"aiuibuilder {args}", subcommand="aiuibuilder", arguments=args,
        platform="discord", respond=respond, metadata={}, notify_channel=notify,
    )


def _router(mapping, tasks_client):
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
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
    # New unified not-linked card: Discord ctx without respond_components falls
    # back to the friendly self-service text (no person's name).
    assert captured, "expected a not-linked response"
    assert any("Link my account" in m for m in captured)
    assert all("Lukas" not in m for m in captured)
    assert all("isn't linked" not in m for m in captured)


@pytest.mark.asyncio
async def test_build_missing_description_shows_usage():
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock(); tc.list_templates = AsyncMock(return_value=[])
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "build", captured))
    assert any("Usage" in m for m in captured)
    tc.start_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_happy_path_starts_and_acks(monkeypatch):
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "todo-a1b2", "status": "running"})
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug, **kw):
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
    tc.list_templates = AsyncMock(return_value=[])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build a todo list", captured, notify=None)
    )
    assert tc.start_build.call_args.args[1] == "a todo list"


@pytest.mark.asyncio
async def test_build_429_says_already_running():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[])
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


@pytest.mark.asyncio
async def test_watch_build_notifies_on_completed():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=[
        {"status": "running", "slug": "s"},
        {"status": "completed", "slug": "s",
         "preview_url": "https://ai-ui.coolestdomain.win/tasks/preview-app/s/"},
    ])
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert len(notified) == 1
    assert "https://ai-ui.coolestdomain.win/tasks/preview-app/s/" in notified[0]


@pytest.mark.asyncio
async def test_watch_build_notifies_on_needs_input():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={
        "status": "needs_input", "slug": "s",
        "error": "Which color theme — light or dark?"})
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert len(notified) == 1
    assert "more detail" in notified[0].lower()
    assert "color theme" in notified[0]


@pytest.mark.asyncio
async def test_watch_build_notifies_on_failed():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={"status": "failed", "slug": "s"})
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert len(notified) == 1
    assert "failed" in notified[0].lower()


@pytest.mark.asyncio
async def test_watch_build_timeout_message():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={"status": "running", "slug": "s"})
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=3)
    assert len(notified) == 1
    assert "still building" in notified[0].lower()


@pytest.mark.asyncio
async def test_watch_build_survives_transient_errors():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=[
        TasksAPIError(0, "boom"),
        {"status": "completed", "slug": "s",
         "preview_url": "https://ai-ui.coolestdomain.win/tasks/preview-app/s/"},
    ])
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert any("preview-app/s/" in m for m in notified)


@pytest.mark.asyncio
async def test_watch_build_gives_up_after_max_consecutive_errors():
    notified = []
    async def notify(msg):
        notified.append(msg)
    ctx = _ctx("100", "build x", [], notify=notify)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=TasksAPIError(0, "boom"))
    r = _router({"100": "a@x.com"}, tc)
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=20)
    assert len(notified) == 1
    assert "Lost track" in notified[0]
    assert tc.get_build_status.call_count == BUILD_MAX_CONSECUTIVE_ERRORS


@pytest.mark.asyncio
async def test_watch_build_noop_when_notify_channel_none():
    ctx = _ctx("100", "build x", [], notify=None)
    tc = MagicMock()
    tc.get_build_status = AsyncMock()
    r = _router({"100": "a@x.com"}, tc)
    # Returns immediately without polling when there's no channel to notify.
    await r._watch_build(ctx, "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    tc.get_build_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_templates_action_lists():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "personal showcase", "has_app": True, "note": ""},
        {"key": "crud", "label": "CRUD app", "emoji": "📝",
         "description": "manage records", "has_app": True, "note": "saves in your browser"},
    ])
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "templates", captured))
    reply = captured[-1]
    assert "portfolio" in reply and "crud" in reply
    assert "saves in your browser" in reply
    # No-emoji preference: the catalog carries emoji glyphs but the listing
    # must not render them.
    assert "🎨" not in reply and "📝" not in reply


@pytest.mark.asyncio
async def test_build_with_known_template_key(monkeypatch):
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "x", "has_app": True, "note": ""}])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "portfolio-a1b2", "status": "running"})
    monkeypatch.setattr(CommandRouter, "_watch_build",
                        lambda self, ctx, email, task_id, slug: _noop())
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build portfolio a UX designer named Maya", captured, notify=None))
    assert tc.start_build.call_args.kwargs["template_key"] == "portfolio"
    assert tc.start_build.call_args.args[1] == "a UX designer named Maya"
    assert any("Building" in m for m in captured)


@pytest.mark.asyncio
async def test_build_unknown_first_word_is_template_less():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "x", "has_app": True, "note": ""}])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build a kanban board for my team", captured, notify=None))
    assert tc.start_build.call_args.kwargs["template_key"] is None
    assert tc.start_build.call_args.args[1] == "a kanban board for my team"


@pytest.mark.asyncio
async def test_build_catalog_failure_falls_back_template_less():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(side_effect=TasksAPIError(0, "down"))
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build portfolio something", captured, notify=None))
    assert tc.start_build.call_args.kwargs["template_key"] is None
    assert tc.start_build.call_args.args[1] == "portfolio something"


@pytest.mark.asyncio
async def test_build_key_only_synthesizes_description():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=[
        {"key": "portfolio", "label": "Portfolio", "emoji": "🎨",
         "description": "x", "has_app": True, "note": ""}])
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s", "status": "running"})
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(
        _ctx("100", "build portfolio", captured, notify=None))
    assert tc.start_build.call_args.kwargs["template_key"] == "portfolio"
    assert tc.start_build.call_args.args[1] == "a Portfolio"


@pytest.mark.asyncio
async def test_templates_action_error_replies_gracefully():
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(side_effect=TasksAPIError(0, "down"))
    await _router({"100": "a@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "templates", captured))
    # _format_build_error maps status 0 → "Tasks service unreachable, try again."
    assert any("unreachable" in m.lower() for m in captured)
