"""Sub-project 2 (reliability basics): friendly names, guaranteed delivery,
and a mid-build reassurance ping. Reuses the build-watcher test pattern from
test_aiuibuilder_build.py (drive _watch_build directly with poll_seconds=0)."""
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import (
    CommandRouter, CommandContext, friendly_name, BUILD_MAX_CONSECUTIVE_ERRORS,
)
from clients.tasks import TasksAPIError


def _ctx(notify):
    async def respond(msg):
        pass
    return CommandContext(
        user_id="100", user_name="t", channel_id="c1", raw_text="build x",
        subcommand="aiuibuilder", arguments="build x", platform="discord",
        respond=respond, metadata={}, notify_channel=notify,
    )


def _router(tasks_client):
    if not isinstance(getattr(tasks_client, "resolve_link", None), AsyncMock):
        tasks_client.resolve_link = AsyncMock(return_value=None)
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map={"100": "a@x.com"}, tasks_client=tasks_client,
    )


# --- friendly_name ---

def test_friendly_name_basic():
    assert friendly_name("A simple feedback form for my shop") == \
        "Simple feedback form for my shop"


def test_friendly_name_strips_article_and_first_clause():
    assert friendly_name("a todo list with dark mode - and tags") == \
        "Todo list with dark mode"


def test_friendly_name_empty():
    assert friendly_name("   ") == ""


def test_friendly_name_long_truncates():
    n = friendly_name("build me " + "x" * 100)
    assert len(n) <= 60


# --- watcher reliability ---

@pytest.mark.asyncio
async def test_watch_build_posts_one_reassurance_then_completes():
    notified = []
    async def notify(msg):
        notified.append(msg)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=[
        {"status": "running", "slug": "s"},
        {"status": "running", "slug": "s"},
        {"status": "running", "slug": "s"},
        {"status": "running", "slug": "s"},  # i==3 -> reassurance fires
        {"status": "completed", "slug": "s",
         "preview_url": "https://x/preview-app/s/"},
    ])
    await _router(tc)._watch_build(
        _ctx(notify), "a@x.com", "t1", "s", poll_seconds=0, max_polls=10)
    assert sum("still building" in m.lower() for m in notified) == 1
    assert any("preview-app/s/" in m for m in notified)


@pytest.mark.asyncio
async def test_watch_build_guarantees_message_on_unexpected_crash():
    notified = []
    async def notify(msg):
        notified.append(msg)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=RuntimeError("kaboom"))
    await _router(tc)._watch_build(
        _ctx(notify), "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert len(notified) == 1
    assert "lost track" in notified[0].lower()


@pytest.mark.asyncio
async def test_watch_build_treats_httpx_error_as_transient():
    notified = []
    async def notify(msg):
        notified.append(msg)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(side_effect=[
        httpx.ReadError("flaky"),
        {"status": "completed", "slug": "s",
         "preview_url": "https://x/preview-app/s/"},
    ])
    await _router(tc)._watch_build(
        _ctx(notify), "a@x.com", "t1", "s", poll_seconds=0, max_polls=5)
    assert any("preview-app/s/" in m for m in notified)


@pytest.mark.asyncio
async def test_watch_build_uses_friendly_display_name():
    notified = []
    async def notify(msg):
        notified.append(msg)
    tc = MagicMock()
    tc.get_build_status = AsyncMock(return_value={"status": "failed", "slug": "feedback-9f2"})
    await _router(tc)._watch_build(
        _ctx(notify), "a@x.com", "t1", "feedback-9f2",
        display_name="My feedback form", poll_seconds=0, max_polls=2)
    assert any("My feedback form" in m for m in notified)
