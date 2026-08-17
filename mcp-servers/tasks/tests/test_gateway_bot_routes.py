"""Saving a bot, without a database.

The DB-backed behaviour lives in test_gateway_bot_routes_db.py, which only runs
in the container. What is tested here is the part that must hold regardless of
storage: a token that Telegram rejects is never written, and a token never
comes back to the browser.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")
os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")
os.environ.setdefault("GATEWAY_PUBLIC_URL", "https://io.example")

import routes_gateway
import telegram_api
from auth import CurrentUser, current_user


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(routes_gateway.page_router)
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        email="ralph@example.com")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def telegram_rejects(monkeypatch):
    async def _get_me(token):
        raise telegram_api.TelegramError("Unauthorized")
    monkeypatch.setattr(routes_gateway.telegram_api, "get_me", _get_me)


@pytest.fixture
def no_writes(monkeypatch):
    """Fails loudly if the route reaches the database at all."""
    written = []

    class Boom:
        async def __aenter__(self):
            written.append("opened")
            raise AssertionError("the route opened a session it should not have")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(routes_gateway, "session", lambda: Boom())
    return written


def test_a_token_telegram_rejects_is_never_stored(client, telegram_rejects, no_writes):
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram", "token": "123:bad",
                             "allowed_ids": ""})
    assert resp.status_code == 400
    assert no_writes == []


def test_the_rejection_says_what_telegram_said(client, telegram_rejects, no_writes):
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram", "token": "123:bad",
                             "allowed_ids": ""})
    assert "Unauthorized" in resp.json()["detail"]


def test_an_unsupported_platform_is_refused_before_any_network_call(client, no_writes):
    # Signal is on the page as planned, and cannot honour a save. This used to
    # use Discord, which now CAN take your own bot — so the case had to move
    # rather than be deleted: the guard it protects is that an unknown platform
    # is refused by the allowlist before any credential is sent anywhere.
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "signal", "token": "x",
                             "allowed_ids": ""})
    assert resp.status_code == 400
    assert "not" in resp.json()["detail"].lower()
    assert no_writes == []


def test_a_whitespace_token_is_refused_before_telegram_is_asked(client, no_writes):
    # Field(min_length=1) passes three spaces, so the strip() check is what
    # catches this. Deterministically a 400, not a 422.
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram", "token": "   ",
                             "allowed_ids": ""})
    assert resp.status_code == 400
    assert "token" in resp.json()["detail"].lower()
