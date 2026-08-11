"""Parsing real Telegram update payloads.

parse_inbound must be pure and synchronous: no network, no disk. A voice memo
carries a file_id that has to be exchanged for a download URL, so the reference
travels on the event and the fetch happens later, in the pipeline.
"""
import httpx
import pytest
import respx

from gateway.events import MessageType
from gateway.platforms.telegram import TELEGRAM_MAX_MESSAGE, TelegramAdapter

API = "https://api.telegram.org/botTEST-TOKEN"


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    a = TelegramAdapter(token="TEST-TOKEN", webhook_secret="hook-secret")
    a.max_message_length = TELEGRAM_MAX_MESSAGE
    a.name = "telegram"
    return a


def _dm(**over) -> dict:
    message = {
        "message_id": 5,
        "from": {"id": 111, "first_name": "Ralph", "username": "ralph"},
        "chat": {"id": 111, "type": "private"},
        "date": 1754870000,
        "text": "hello",
    }
    message.update(over)
    return {"update_id": 900, "message": message}


def test_a_direct_text_message_parses(adapter):
    event = adapter.parse_inbound(_dm(), {})
    assert event.text == "hello"
    assert event.message_type is MessageType.TEXT
    assert event.source.platform == "telegram"
    assert event.source.chat_id == "111"
    assert event.source.user_id == "111"
    assert event.source.chat_type == "dm"
    assert event.source.user_name == "Ralph"
    assert event.message_id == "5"


def test_a_group_message_keeps_its_real_chat_type(adapter):
    # The pipeline refuses on this value, so it must not be normalized to "dm".
    payload = _dm(chat={"id": -100, "type": "supergroup"})
    assert adapter.parse_inbound(payload, {}).source.chat_type == "supergroup"


def test_a_voice_memo_carries_a_file_id_a_duration_and_no_text(adapter):
    payload = _dm(text=None, voice={"file_id": "AwACAgQ", "duration": 7,
                                    "mime_type": "audio/ogg", "file_size": 8000})
    event = adapter.parse_inbound(payload, {})
    assert event.message_type is MessageType.VOICE
    assert event.media_ref == "AwACAgQ"
    assert event.media_duration == 7
    assert event.text == ""


def test_a_voice_memo_without_a_duration_does_not_invent_one(adapter):
    payload = _dm(text=None, voice={"file_id": "AwACAgQ"})
    assert adapter.parse_inbound(payload, {}).media_duration is None


def test_a_photo_is_typed_but_not_fetched(adapter):
    payload = _dm(text=None, photo=[{"file_id": "small"}, {"file_id": "large"}],
                  caption="look")
    event = adapter.parse_inbound(payload, {})
    assert event.message_type is MessageType.PHOTO
    assert event.media_ref == "large"          # Telegram sends sizes ascending
    assert event.text == "look"


@pytest.mark.parametrize("payload", [
    {"update_id": 1},                                       # nothing we handle
    {"update_id": 1, "edited_message": {"text": "x"}},      # an edit
    {"update_id": 1, "callback_query": {"id": "q"}},        # a button press
    {"update_id": 1, "channel_post": {"text": "x"}},        # a channel
])
def test_updates_we_do_not_handle_parse_to_none(adapter, payload):
    assert adapter.parse_inbound(payload, {}) is None


def test_a_malformed_payload_parses_to_none_rather_than_raising(adapter):
    assert adapter.parse_inbound({"message": "not a dict"}, {}) is None


def test_the_webhook_secret_is_checked(adapter):
    assert adapter.verify_webhook({}, {"x-telegram-bot-api-secret-token": "hook-secret"})
    assert not adapter.verify_webhook({}, {"x-telegram-bot-api-secret-token": "wrong"})
    assert not adapter.verify_webhook({}, {})


def test_header_matching_is_case_insensitive(adapter):
    assert adapter.verify_webhook({}, {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})


@respx.mock
async def test_send_posts_to_send_message(adapter):
    import json
    route = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True}))

    await adapter.send("111", "hi")

    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == "111"
    assert body["text"] == "hi"


@respx.mock
async def test_a_send_failure_is_logged_and_not_raised(adapter, caplog):
    respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(400, json={"ok": False,
                                               "description": "chat not found"}))
    await adapter.send("111", "hi")          # must not raise
    assert "chat not found" in caplog.text


@respx.mock
async def test_connect_registers_the_webhook_with_its_secret(adapter):
    import json
    route = respx.post(f"{API}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True}))

    assert await adapter.connect() is True

    body = json.loads(route.calls[0].request.content)
    assert body["url"].endswith("/webhook/telegram")
    assert body["secret_token"] == "hook-secret"
    assert "message" in body["allowed_updates"]


@respx.mock
async def test_connect_returns_false_instead_of_raising(adapter):
    # One misconfigured platform must not stop the service from starting.
    respx.post(f"{API}/setWebhook").mock(side_effect=httpx.ConnectError("down"))
    assert await adapter.connect() is False


@respx.mock
async def test_disconnect_deletes_the_webhook(adapter):
    route = respx.post(f"{API}/deleteWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    await adapter.disconnect()
    assert route.called
