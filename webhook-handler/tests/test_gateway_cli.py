"""The CLI adapter and its route.

The device id is the only credential on this path, so the format check and the
"unknown device gets a code, nothing else" behaviour are both load-bearing.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main
from gateway.events import MessageType
from gateway.platforms.cli import CliAdapter

DEVICE = "a" * 32


@pytest.fixture
def adapter():
    a = CliAdapter()
    a.name = "cli"
    a.max_message_length = 0
    return a


def test_a_valid_body_parses_to_a_dm_event(adapter):
    event = adapter.parse_inbound(
        {"device_id": DEVICE, "device_name": "dev-box", "text": "hello"}, {})

    assert event.text == "hello"
    assert event.message_type is MessageType.TEXT
    assert event.source.platform == "cli"
    assert event.source.chat_id == DEVICE
    assert event.source.user_id == DEVICE
    assert event.source.chat_type == "dm"
    assert event.source.user_name == "dev-box"


@pytest.mark.parametrize("device_id", [
    "", "short", "z" * 32, "A" * 31, "a" * 33, None, 12345,
])
def test_a_malformed_device_id_parses_to_none(adapter, device_id):
    assert adapter.parse_inbound({"device_id": device_id, "text": "hi"}, {}) is None


def test_a_missing_text_parses_to_none(adapter):
    assert adapter.parse_inbound({"device_id": DEVICE}, {}) is None


async def test_send_is_a_no_op(adapter):
    # The route returns the reply, so send must do nothing and say nothing.
    assert await adapter.send(DEVICE, "anything") is None


async def test_connect_needs_nothing(adapter):
    assert await adapter.connect() is True
    assert await adapter.disconnect() is None


@pytest.fixture
def client(monkeypatch, adapter):
    monkeypatch.setattr(main.gateway_registry, "adapter",
                        lambda name: adapter if name == "cli" else None)
    return TestClient(main.app)


def test_the_route_returns_the_reply_inline(client, monkeypatch):
    async def fake_handle(event, adapter_):
        return f"you said: {event.text}"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)

    resp = client.post("/webhook/gateway/cli",
                       json={"device_id": DEVICE, "device_name": "dev-box",
                             "text": "hello"})

    assert resp.status_code == 200
    assert resp.json() == {"reply": "you said: hello"}


def test_a_bad_device_id_is_400_and_never_reaches_the_pipeline(client, monkeypatch):
    called = []
    monkeypatch.setattr(main.gateway_pipeline, "handle_event",
                        AsyncMock(side_effect=lambda *a: called.append(1)))

    resp = client.post("/webhook/gateway/cli",
                       json={"device_id": "nope", "text": "hello"})

    assert resp.status_code == 400
    assert called == []


def test_the_route_is_synchronous_unlike_telegram(client, monkeypatch):
    # No 200-then-work here: there is no re-delivery to defend against and the
    # caller is blocked on the answer.
    async def fake_handle(event, adapter_):
        return "done"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)
    assert client.post("/webhook/gateway/cli",
                       json={"device_id": DEVICE, "text": "x"}).json()["reply"] == "done"
