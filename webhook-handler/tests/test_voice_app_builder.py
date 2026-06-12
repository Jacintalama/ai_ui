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
