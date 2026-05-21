"""webhook-handler/scripts/setup_app_builder_channel.py orchestration (helpers monkeypatched)."""
import os
import sys

import pytest

# The script lives in webhook-handler/scripts/ (sibling of this tests/ dir's
# parent); add that dir to sys.path so it can be imported.
_WEBHOOK_HANDLER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_WEBHOOK_HANDLER, "scripts"))

import setup_app_builder_channel as setup  # noqa: E402


def _clear_env(monkeypatch):
    for k in ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "APP_BUILDER_SETUP_EMAIL",
              "ADMIN_EMAILS", "TASKS_URL", "APP_BUILDER_CHANNEL_NAME",
              "APP_BUILDER_RESET"):
        monkeypatch.delenv(k, raising=False)


def test_missing_token_or_guild_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    assert setup.main() == 1


def test_missing_email_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    assert setup.main() == 1


def test_happy_path_creates_and_pins(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    calls = {}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: None)
    monkeypatch.setattr(setup, "_create_channel",
                        lambda g, n, h: calls.update({"created": "chan-1"}) or "chan-1")
    monkeypatch.setattr(setup, "_post_panel",
                        lambda c, p, h: calls.update({"posted": (c, p)}) or "msg-1")
    monkeypatch.setattr(setup, "_pin",
                        lambda c, m, h: calls.setdefault("pinned", (c, m)))

    assert setup.main() == 0
    assert calls["created"] == "chan-1"
    assert calls["posted"][0] == "chan-1"
    assert "components" in calls["posted"][1]  # a real panel payload was posted
    assert calls["pinned"] == ("chan-1", "msg-1")


def test_reuses_existing_channel(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    created = {"n": 0}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "landing", "label": "Landing", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: "existing-1")
    monkeypatch.setattr(setup, "_create_channel",
                        lambda g, n, h: created.__setitem__("n", created["n"] + 1) or "new")
    monkeypatch.setattr(setup, "_post_panel", lambda c, p, h: "msg-2")
    monkeypatch.setattr(setup, "_pin", lambda c, m, h: None)

    assert setup.main() == 0
    assert created["n"] == 0  # never created a second channel


def test_catalog_fetch_failure_returns_2(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: (_ for _ in ()).throw(Exception("conn refused")))
    assert setup.main() == 2


def test_empty_catalog_returns_2(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    monkeypatch.setattr(setup, "_fetch_templates", lambda url, email: [])
    assert setup.main() == 2


def test_reset_deletes_existing_channel_then_recreates(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    monkeypatch.setenv("APP_BUILDER_RESET", "1")

    calls = {}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: "old-chan")
    monkeypatch.setattr(setup, "_delete_channel",
                        lambda c, h: calls.update({"deleted": c}))
    monkeypatch.setattr(setup, "_create_channel",
                        lambda g, n, h: calls.update({"created": "new-chan"}) or "new-chan")
    monkeypatch.setattr(setup, "_post_panel", lambda c, p, h: "msg-1")
    monkeypatch.setattr(setup, "_pin", lambda c, m, h: None)

    assert setup.main() == 0
    assert calls["deleted"] == "old-chan"
    assert calls["created"] == "new-chan"


def test_no_reset_keeps_existing_channel(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    deleted = {"n": 0}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: "old-chan")
    monkeypatch.setattr(setup, "_delete_channel",
                        lambda c, h: deleted.__setitem__("n", deleted["n"] + 1))
    monkeypatch.setattr(setup, "_create_channel", lambda g, n, h: "x")
    monkeypatch.setattr(setup, "_post_panel", lambda c, p, h: "msg-1")
    monkeypatch.setattr(setup, "_pin", lambda c, m, h: None)

    assert setup.main() == 0
    assert deleted["n"] == 0
