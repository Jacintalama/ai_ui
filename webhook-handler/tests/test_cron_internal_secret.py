"""Regression: the CommandRouter must hand the internal callback secret to the
TasksClient it builds. Without it, system calls to /discord-links/* (used by
the cron 'Open my schedules' dashboard) send an empty X-Internal-Secret and the
tasks service rejects them with 403 'invalid internal secret'.
"""
from unittest.mock import MagicMock

from handlers.commands import CommandRouter


def test_router_builds_tasks_client_with_internal_secret(monkeypatch):
    import config
    monkeypatch.setattr(config.settings, "internal_callback_secret", "secret-xyz")
    monkeypatch.setattr(config.settings, "tasks_url", "http://tasks:8210")

    router = CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=None,  # force it to build its own client from settings
    )

    assert router._tasks_client._internal_secret == "secret-xyz"
