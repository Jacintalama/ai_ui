"""/webhook/voice/{command} routing: special-cases + last-build memory."""
import sys
import types

import pytest
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Stub optional hard deps BEFORE importing main (same pattern as
# test_format_schedule_result.py — keep in sync with it). If the REAL
# voice_bot/discord are already imported (by other test modules), setdefault
# keeps them — both satisfy main's imports.
# ---------------------------------------------------------------------------
_stub_voice_bot = types.ModuleType("voice_bot")


async def _noop_start_voice_bot(*args, **kwargs):
    return None


_stub_voice_bot.start_voice_bot = _noop_start_voice_bot
_stub_voice_bot.current_text_channel_id = lambda: None
_stub_voice_bot.current_guild_id = lambda: None
sys.modules.setdefault("voice_bot", _stub_voice_bot)
for _mod in (
    "audioop",
    "discord",
    "discord.ext",
    "discord.ext.voice_recv",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers",
    "apscheduler.triggers.cron",
):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))


class _FakeScheduler:  # minimal apscheduler stand-ins
    def __init__(self, *a, **k):
        self.running = False

    def add_job(self, *a, **k):
        return None

    def start(self, *a, **k):
        self.running = True


class _FakeCronTrigger:
    def __init__(self, *a, **k):
        pass

    @classmethod
    def from_crontab(cls, *a, **k):
        return cls()


if not hasattr(sys.modules["apscheduler.schedulers.asyncio"], "AsyncIOScheduler"):
    sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = _FakeScheduler  # type: ignore[attr-defined]
if not hasattr(sys.modules["apscheduler.triggers.cron"], "CronTrigger"):
    sys.modules["apscheduler.triggers.cron"].CronTrigger = _FakeCronTrigger  # type: ignore[attr-defined]

import main  # noqa: E402
from config import settings  # noqa: E402


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture()
def voice_setup(monkeypatch):
    monkeypatch.setattr(settings, "voice_webhook_secret", "s3cret")
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    router = MagicMock()
    router.execute = AsyncMock()
    router.run_voice_build = AsyncMock(return_value={"task_id": "t9", "slug": "m-1"})
    router.run_voice_build_status = AsyncMock()
    monkeypatch.setattr(main, "command_router", router)
    main._last_voice_build.clear()
    return router


async def test_list_templates_routes_to_aiuibuilder(voice_setup):
    await main.voice_webhook("list_templates", _Req({}), x_voice_secret="s3cret")
    ctx = voice_setup.execute.await_args.args[0]
    assert ctx.subcommand == "aiuibuilder"
    assert ctx.arguments == "templates"
    assert ctx.platform == "voice"


async def test_start_build_remembers_last_build(voice_setup):
    resp = await main.voice_webhook(
        "start_build",
        _Req({"template_key": "restaurant", "description": "a cafe"}),
        x_voice_secret="s3cret",
    )
    voice_setup.run_voice_build.assert_awaited_once()
    args = voice_setup.run_voice_build.await_args.args
    assert args[1] == "restaurant" and args[2] == "a cafe"
    assert main._last_voice_build["task_id"] == "t9"
    assert main._last_voice_build["slug"] == "m-1"
    assert "spoken_summary" in resp


async def test_build_status_uses_remembered_build(voice_setup):
    main._last_voice_build.update(
        {"task_id": "t9", "slug": "m-1", "email": "o@x.com"})
    await main.voice_webhook("build_status", _Req({}), x_voice_secret="s3cret")
    voice_setup.run_voice_build_status.assert_awaited_once()
    args = voice_setup.run_voice_build_status.await_args
    assert args.args[1] == "o@x.com" and args.args[2] == "t9"
    assert args.kwargs.get("slug") == "m-1"


async def test_build_status_without_memory_speaks_no_build(voice_setup):
    resp = await main.voice_webhook("build_status", _Req({}), x_voice_secret="s3cret")
    voice_setup.run_voice_build_status.assert_not_awaited()
    assert "haven't started" in resp["spoken_summary"].lower()


async def test_generic_command_unchanged(voice_setup):
    await main.voice_webhook(
        "status", _Req({"arguments": ""}), x_voice_secret="s3cret")
    ctx = voice_setup.execute.await_args.args[0]
    assert ctx.subcommand == "status"


async def test_bad_secret_rejected(voice_setup):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await main.voice_webhook("status", _Req({}), x_voice_secret="wrong")


# ---------------------------------------------------------------------------
# Build-ready thread button: the voice notify message carries a link button
# that jumps to the user's private App Builder thread (user request
# 2026-06-12: "a button ... proceed me to my thread app builder").
# ---------------------------------------------------------------------------

def test_thread_link_components_shape():
    comps = main._thread_link_components("111", "222")
    assert comps == [{
        "type": 1,
        "components": [{
            "type": 2, "style": 5, "label": "Open my App Builder thread",
            "url": "https://discord.com/channels/111/222",
        }],
    }]


def test_voice_discord_id_reverse_maps_email(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "o@x.com")
    monkeypatch.setattr(settings, "_discord_map_cache", {"123": "o@x.com"},
                        raising=False)
    assert main._voice_discord_id() == "123"


def test_voice_discord_id_none_when_unmapped(monkeypatch):
    monkeypatch.setattr(settings, "voice_user_email", "nobody@x.com")
    monkeypatch.setattr(settings, "_discord_map_cache", {"123": "o@x.com"},
                        raising=False)
    assert main._voice_discord_id() is None
