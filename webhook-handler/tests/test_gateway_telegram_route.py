"""The inbound route.

Telegram re-delivers any update that does not get a fast 200, so returning 200
before doing the work is correctness, not an optimization. A slow model call
would otherwise have the same message processed several times.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import main
from gateway.events import MessageEvent, MessageType, SessionSource

GOOD = {"x-telegram-bot-api-secret-token": "hook-secret"}


def _update(update_id: int = 900) -> dict:
    return {"update_id": update_id, "message": {
        "message_id": 5,
        "from": {"id": 111, "first_name": "Ralph"},
        "chat": {"id": 111, "type": "private"},
        "date": 1754870000, "text": "hello"}}


@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    # verify_webhook and parse_inbound are synchronous by contract (base.py), so
    # they need synchronous doubles. A bare AsyncMock hands back a coroutine for
    # every attribute, which is truthy and never None, so the bad-secret and
    # unparseable-update tests would pass no matter what the route did.
    a.verify_webhook = MagicMock(return_value=True)
    a.parse_inbound = MagicMock(return_value=MessageEvent(
        text="hello", message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="111",
                             user_id="111", chat_type="dm")))
    return a


@pytest.fixture
def client(monkeypatch, adapter):
    monkeypatch.setattr(main.gateway_registry, "adapter",
                        lambda name: adapter if name == "telegram" else None)
    monkeypatch.setattr(main, "_gateway_seen_updates", set())
    return TestClient(main.app)


def test_a_valid_update_is_accepted_immediately(client, adapter, monkeypatch):
    handled = asyncio.Event()

    async def fake_handle(event, adapter_):
        handled.set()
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)

    resp = client.post("/webhook/telegram", json=_update(), headers=GOOD)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_a_bad_secret_is_200_and_ignored(client, adapter, monkeypatch):
    # A non-200 would make Telegram retry this forever.
    adapter.verify_webhook.return_value = False
    called = []
    monkeypatch.setattr(main.gateway_pipeline, "handle_event",
                        AsyncMock(side_effect=lambda *a: called.append(1)))

    resp = client.post("/webhook/telegram", json=_update(),
                       headers={"x-telegram-bot-api-secret-token": "wrong"})

    assert resp.status_code == 200
    assert called == []


def test_a_duplicate_update_id_is_dropped(client, adapter, monkeypatch):
    seen = []

    async def fake_handle(event, adapter_):
        seen.append(1)
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)

    client.post("/webhook/telegram", json=_update(77), headers=GOOD)
    client.post("/webhook/telegram", json=_update(77), headers=GOOD)

    assert len(seen) == 1


def test_the_route_503s_when_telegram_is_not_configured(monkeypatch):
    monkeypatch.setattr(main.gateway_registry, "adapter", lambda name: None)
    resp = TestClient(main.app).post("/webhook/telegram", json=_update(),
                                     headers=GOOD)
    assert resp.status_code == 503


def test_an_unparseable_update_is_200_and_does_nothing(client, adapter, monkeypatch):
    adapter.parse_inbound.return_value = None
    called = []
    monkeypatch.setattr(main.gateway_pipeline, "handle_event",
                        AsyncMock(side_effect=lambda *a: called.append(1)))

    resp = client.post("/webhook/telegram", json={"update_id": 5}, headers=GOOD)

    assert resp.status_code == 200
    assert called == []
