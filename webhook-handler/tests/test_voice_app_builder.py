"""Voice App Builder flow: identity, run_voice_build, run_voice_build_status."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from config import settings
from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _voice_ctx(captured, command="aiuibuilder", arguments="", notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id="voice-agent", user_name="Voice User", channel_id="voice",
        raw_text=f"{command} {arguments}".strip(), subcommand=command,
        arguments=arguments, platform="voice", respond=respond,
        metadata={"source": "elevenlabs"}, notify_channel=notify,
    )


def _router(tasks_client):
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=tasks_client,
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_email_resolves_from_setting(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "Owner@Example.COM")
    router = _router(MagicMock())
    email = await router._resolve_email_for_ctx(_voice_ctx([]))
    assert email == "owner@example.com"


@pytest.mark.asyncio
async def test_voice_email_none_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "")
    router = _router(MagicMock())
    assert await router._resolve_email_for_ctx(_voice_ctx([])) is None


# ---------------------------------------------------------------------------
# run_voice_build
# ---------------------------------------------------------------------------

CATALOG = [
    {"key": "restaurant", "label": "Restaurant", "description": "menus"},
    {"key": "portfolio", "label": "Portfolio", "description": "showcase"},
]


@pytest.mark.asyncio
async def test_voice_build_not_linked_spoken(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "")
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    await _router(tc).run_voice_build(_voice_ctx(captured), None, "a cafe site")
    assert captured and "VOICE_USER_EMAIL" in captured[-1]
    tc.start_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_build_template_happy_path(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=CATALOG)
    tc.start_build = AsyncMock(return_value={"task_id": "t9", "slug": "marios-1234"})
    watched = {}
    async def fake_watch(self, ctx, email, task_id, slug):
        watched["args"] = (email, task_id, slug)
    monkeypatch.setattr(CommandRouter, "_watch_build", fake_watch)
    async def notify(msg):
        pass

    result = await _router(tc).run_voice_build(
        _voice_ctx(captured, notify=notify), "Restaurant", "a site called Marios",
    )
    import asyncio as _a; await _a.sleep(0)
    assert result == {"task_id": "t9", "slug": "marios-1234"}
    tc.start_build.assert_awaited_once()
    assert tc.start_build.call_args.kwargs.get("template_key") == "restaurant"
    assert tc.start_build.call_args.args[1] == "a site called Marios"
    assert any("marios-1234" in m for m in captured)
    assert watched["args"] == ("o@x.com", "t9", "marios-1234")


@pytest.mark.asyncio
async def test_voice_build_blank_project_no_template(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"task_id": "t1", "slug": "s-1"})
    result = await _router(tc).run_voice_build(_voice_ctx(captured), None, "a blog")
    assert result == {"task_id": "t1", "slug": "s-1"}
    assert tc.start_build.call_args.kwargs.get("template_key") is None
    tc.list_templates.assert_not_called()  # no catalog fetch for blank builds


@pytest.mark.asyncio
async def test_voice_build_unknown_template_spoken_error(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.list_templates = AsyncMock(return_value=CATALOG)
    tc.start_build = AsyncMock()
    result = await _router(tc).run_voice_build(
        _voice_ctx(captured), "spaceship", "a site")
    assert result is None
    tc.start_build.assert_not_awaited()
    assert any("spaceship" in m for m in captured)


@pytest.mark.asyncio
async def test_voice_build_empty_description_rejected(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    result = await _router(tc).run_voice_build(_voice_ctx(captured), None, "   ")
    assert result is None
    tc.start_build.assert_not_awaited()
    assert any("describe" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_voice_build_tasks_error_spoken(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(side_effect=TasksAPIError(429, "busy"))
    result = await _router(tc).run_voice_build(_voice_ctx(captured), None, "a blog")
    assert result is None
    assert captured, "expected a spoken error"


# ---------------------------------------------------------------------------
# run_voice_build_status
# ---------------------------------------------------------------------------

async def _status_reply(status_payload, *, error=None):
    captured = []
    tc = MagicMock()
    if error is not None:
        tc.get_build_status = AsyncMock(side_effect=error)
    else:
        tc.get_build_status = AsyncMock(return_value=status_payload)
    await _router(tc).run_voice_build_status(
        _voice_ctx(captured), "o@x.com", "t9", slug="marios-1234")
    return captured


@pytest.mark.asyncio
async def test_build_status_running():
    captured = await _status_reply({"status": "running"})
    assert any("still building" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_build_status_completed_names_url():
    captured = await _status_reply(
        {"status": "completed", "preview_url": "https://x/preview-app/marios-1234/"})
    joined = " ".join(captured).lower()
    assert "ready" in joined and "marios-1234" in joined


@pytest.mark.asyncio
async def test_build_status_failed():
    captured = await _status_reply({"status": "failed"})
    assert any("failed" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_build_status_needs_input_includes_detail():
    captured = await _status_reply(
        {"status": "needs_input", "error": "Which city is the restaurant in?"})
    joined = " ".join(captured)
    assert "Which city" in joined


@pytest.mark.asyncio
async def test_build_status_api_error_spoken():
    captured = await _status_reply(None, error=TasksAPIError(0, "down"))
    assert any("try again" in m.lower() for m in captured)
