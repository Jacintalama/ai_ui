"""scripts/setup_slack_app_builder_channel.py orchestration (helpers patched)."""
import os
import sys

import pytest

# Make the scripts/ dir importable (repo_root/scripts).
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import setup_slack_app_builder_channel as setup  # noqa: E402


def _clear_env(monkeypatch):
    for k in ("SLACK_BOT_TOKEN", "APP_BUILDER_SETUP_EMAIL", "ADMIN_EMAILS",
              "TASKS_URL", "SLACK_APP_BUILDER_CHANNEL"):
        monkeypatch.delenv(k, raising=False)


def test_missing_token_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    assert setup.main() == 1


def test_missing_email_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-tok")
    assert setup.main() == 1


def test_happy_path_creates_and_pins(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-tok")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    calls = {}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda client, token, name: None)
    monkeypatch.setattr(setup, "_create_channel",
                        lambda client, token, name: calls.update({"created": "C1"}) or "C1")
    monkeypatch.setattr(setup, "_join_channel",
                        lambda client, token, cid: calls.update({"joined": cid}))
    monkeypatch.setattr(setup, "_post_panel",
                        lambda client, token, cid, blocks: calls.update({"posted": (cid, blocks)}) or "ts-1")
    monkeypatch.setattr(setup, "_pin",
                        lambda client, token, cid, ts: calls.setdefault("pinned", (cid, ts)))

    assert setup.main() == 0
    assert calls["created"] == "C1"
    assert calls["joined"] == "C1"
    assert calls["posted"][0] == "C1"
    # a real Block Kit panel was posted (has an actions block of buttons)
    blocks = calls["posted"][1]
    assert any(b.get("type") == "actions" for b in blocks)
    assert calls["pinned"] == ("C1", "ts-1")


def test_reuses_existing_channel(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-tok")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    created = {"n": 0}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "landing", "label": "Landing", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda client, token, name: "existing-1")
    monkeypatch.setattr(setup, "_create_channel",
                        lambda client, token, name: created.__setitem__("n", created["n"] + 1) or "new")
    monkeypatch.setattr(setup, "_join_channel", lambda client, token, cid: None)
    monkeypatch.setattr(setup, "_post_panel", lambda client, token, cid, blocks: "ts-2")
    monkeypatch.setattr(setup, "_pin", lambda client, token, cid, ts: None)

    assert setup.main() == 0
    assert created["n"] == 0  # never created a second channel


def test_catalog_fetch_failure_returns_2(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-tok")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: (_ for _ in ()).throw(Exception("conn refused")))
    assert setup.main() == 2


def test_empty_catalog_returns_2(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-tok")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    monkeypatch.setattr(setup, "_fetch_templates", lambda url, email: [])
    assert setup.main() == 2
