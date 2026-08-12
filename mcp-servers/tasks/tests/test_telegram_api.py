"""The only place tasks talks to api.telegram.org.

Tests drive the module-level _client_factory seam, the same pattern the app
post-processing modules use, so nothing here touches the network.
"""
import pytest

import telegram_api as tg


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Records every call so a test can assert on the URL as well as the body."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload or {"ok": True, "result": {}}
        self.raises = raises
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        self.calls.append((url, json))
        if self.raises:
            raise self.raises
        return FakeResponse(self.payload)


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(tg, "_client_factory", lambda **kw: client)
    return client


async def test_get_me_returns_the_bot_identity(fake):
    fake.payload = {"ok": True, "result": {"id": 42, "username": "ralphs_io_bot"}}
    assert await tg.get_me("123:AAH") == {"id": 42, "username": "ralphs_io_bot"}


async def test_get_me_raises_what_telegram_actually_said(fake):
    fake.payload = {"ok": False, "description": "Unauthorized"}
    with pytest.raises(tg.TelegramError) as err:
        await tg.get_me("123:AAH")
    assert err.value.description == "Unauthorized"


async def test_a_network_failure_is_also_a_telegram_error(fake):
    # The caller has one thing to catch, so a save cannot 500 on a timeout.
    fake.raises = RuntimeError("connect timeout")
    with pytest.raises(tg.TelegramError):
        await tg.get_me("123:AAH")


async def test_set_webhook_sends_the_url_and_the_secret(fake):
    await tg.set_webhook("123:AAH", "https://io.example/webhook/telegram/abc",
                         "s3cret")
    url, body = fake.calls[0]
    assert url.endswith("/setWebhook")
    assert body["url"] == "https://io.example/webhook/telegram/abc"
    assert body["secret_token"] == "s3cret"


async def test_the_token_is_in_the_url_telegram_requires_and_nowhere_else(fake):
    await tg.delete_webhook("123:AAH")
    url, body = fake.calls[0]
    assert url == "https://api.telegram.org/bot123:AAH/deleteWebhook"
    assert body == {}


async def test_send_message_carries_the_chat_and_the_text(fake):
    await tg.send_message("123:AAH", "555", "IO is connected.")
    url, body = fake.calls[0]
    assert url.endswith("/sendMessage")
    assert body["chat_id"] == "555"
    assert body["text"] == "IO is connected."


async def test_send_message_surfaces_a_rejection(fake):
    fake.payload = {"ok": False, "description": "chat not found"}
    with pytest.raises(tg.TelegramError) as err:
        await tg.send_message("123:AAH", "555", "hi")
    assert err.value.description == "chat not found"
