"""Webhook signature verification must FAIL CLOSED.

Slack/GitHub used to skip verification entirely when the secret was unset
(`if settings.<secret>:`), so a config slip would silently process
unauthenticated requests. When the integration is active but its secret is
missing, the endpoint must reject (503), not process the request. The voice
webhook compares its secret in constant time and must tolerate a missing
header without crashing. (audit 2026-06-15.)
"""
import sys
import types

import pytest
from unittest.mock import AsyncMock, MagicMock

# Stub optional hard deps BEFORE importing main (same pattern as the other
# webhook tests — setdefault keeps the real modules if already imported).
_stub_voice_bot = types.ModuleType("voice_bot")


async def _noop_start_voice_bot(*args, **kwargs):
    return None


_stub_voice_bot.start_voice_bot = _noop_start_voice_bot
_stub_voice_bot.current_text_channel_id = lambda: None
_stub_voice_bot.current_guild_id = lambda: None
sys.modules.setdefault("voice_bot", _stub_voice_bot)
for _mod in (
    "audioop", "discord", "discord.ext", "discord.ext.voice_recv",
    "apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.asyncio",
    "apscheduler.triggers", "apscheduler.triggers.cron",
):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))


class _FakeScheduler:
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

from fastapi import HTTPException  # noqa: E402

import main  # noqa: E402
from config import settings  # noqa: E402


class _Req:
    """Fake Starlette Request with body/json/form."""

    def __init__(self, body: bytes = b"{}"):
        self._body = body

    async def body(self):
        return self._body

    async def json(self):
        import json as _j
        return _j.loads(self._body)

    async def form(self):
        return {}


def _ok_handler():
    """A handler whose fail-OPEN path would succeed (return 200), so a failing
    test means 'verification was skipped', not 'handler crashed'."""
    return MagicMock(handle_event=AsyncMock(return_value={"success": True}),
                     handle_command=AsyncMock(return_value={"ok": True}),
                     handle_interaction=AsyncMock(return_value={"ok": True}))


async def test_github_fails_closed_when_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "github_webhook_secret", "")
    monkeypatch.setattr(main, "github_handler", _ok_handler())
    with pytest.raises(HTTPException) as ei:
        await main.github_webhook(
            _Req(b'{"a":1}'), x_github_event="push",
            x_hub_signature_256=None, x_github_delivery="d1")
    assert ei.value.status_code == 503


async def test_slack_events_fails_closed_when_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", "")
    monkeypatch.setattr(main, "slack_handler", _ok_handler())
    with pytest.raises(HTTPException) as ei:
        await main.slack_webhook(
            _Req(b'{"type":"event_callback"}'),
            x_slack_request_timestamp="1", x_slack_signature="v0=x")
    assert ei.value.status_code == 503


async def test_slack_commands_fails_closed_when_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", "")
    monkeypatch.setattr(main, "slack_command_handler", _ok_handler())
    with pytest.raises(HTTPException) as ei:
        await main.slack_commands_webhook(
            _Req(b"command=/aiui"),
            x_slack_request_timestamp="1", x_slack_signature="v0=x")
    assert ei.value.status_code == 503


async def test_slack_interactions_fails_closed_when_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", "")
    monkeypatch.setattr(main, "slack_interactions_handler", _ok_handler())
    with pytest.raises(HTTPException) as ei:
        await main.slack_interactions_webhook(
            _Req(b"payload=%7B%7D"),
            x_slack_request_timestamp="1", x_slack_signature="v0=x")
    assert ei.value.status_code == 503


async def test_voice_missing_header_rejected_not_crash(monkeypatch):
    """Constant-time compare must still reject a missing header (None) with a
    401, not raise TypeError from hmac.compare_digest(None, ...)."""
    monkeypatch.setattr(settings, "voice_webhook_secret", "s3cret")
    with pytest.raises(HTTPException) as ei:
        await main.voice_webhook("status", _Req(), x_voice_secret=None)
    assert ei.value.status_code == 401
