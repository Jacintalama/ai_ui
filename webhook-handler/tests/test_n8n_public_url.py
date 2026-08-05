"""Error messages must not send users to a page that errors.

Four messages told users to "Check: https://ai-ui.coolestdomain.win/n8n" when a
Gmail or Sheets workflow failed. That path returns 502 — the local n8n container
was removed on 2026-07-09 to reclaim disk, and the team's real n8n is the
separately hosted instance. So the platform's advice for a broken thing was to
go look at another broken thing.

The internal URL (`http://n8n:5678`) is a container address and is useless in a
chat message even when it works, so this is a separate setting rather than a
reuse of `n8n_url`.
"""
import re

from config import settings


def _messages() -> str:
    import pathlib
    return pathlib.Path("handlers/commands.py").read_text(encoding="utf-8")


def test_there_is_a_public_n8n_url_setting():
    assert hasattr(settings, "n8n_public_url")
    assert settings.n8n_public_url, "must have a usable default"


def test_the_public_url_is_not_the_dead_local_path():
    assert "/n8n" not in settings.n8n_public_url.replace("//", "")
    assert "ai-ui.coolestdomain.win/n8n" not in settings.n8n_public_url


def test_the_public_url_is_not_a_container_address():
    """`http://n8n:5678` resolves only inside the docker network; telling a user
    to open it is the same class of unhelpful as the 502."""
    assert "n8n:5678" not in settings.n8n_public_url
    assert settings.n8n_public_url.startswith("https://")


def test_no_message_still_points_at_the_dead_page():
    """The whole point. Catches a fifth copy being added later."""
    offenders = [
        line.strip()
        for line in _messages().splitlines()
        if "ai-ui.coolestdomain.win/n8n" in line
    ]
    assert not offenders, (
        f"{len(offenders)} message(s) still send users to a 502: {offenders[:2]}")


def test_the_messages_use_the_setting_rather_than_a_hardcoded_host():
    """A hardcoded host is how the previous one rotted silently."""
    src = _messages()
    assert "n8n_public_url" in src, (
        "messages should read the setting so moving n8n is a config change")


def test_no_hardcoded_hostinger_host_in_the_messages():
    src = _messages()
    assert "srv1041674" not in src, (
        "the host belongs in config, not in four message strings")
