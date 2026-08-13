"""The Buzz adapter.

Buzz publishes no API of its own, so this contract is one we define and hand
them. That cuts both ways: nothing here can lean on a platform guarantee, so
the adapter has to be strict about what it accepts, and the signature is the
only thing standing between this endpoint and the open internet. Caddy routes
/webhook/* straight to this service, past api-gateway's auth.
"""
import hashlib
import hmac
import json

import pytest

from gateway.events import MessageType
from gateway.platforms.buzz import BuzzAdapter, sign_body

SECRET = "a-shared-secret-between-buzz-and-io"


@pytest.fixture
def adapter():
    a = BuzzAdapter(secret=SECRET)
    a.name = "buzz"
    a.max_message_length = 0
    return a


def body_and_headers(payload, secret=SECRET):
    raw = json.dumps(payload).encode("utf-8")
    return payload, {"x-buzz-signature": sign_body(raw, secret)}, raw


def test_a_body_signed_with_the_shared_secret_is_accepted(adapter):
    payload, headers, raw = body_and_headers(
        {"user_id": "u-42", "user_name": "Ralph", "text": "hello"})
    assert adapter.verify_webhook_body(raw, headers) is True


def test_an_unsigned_body_is_refused(adapter):
    _, _, raw = body_and_headers({"user_id": "u-42", "text": "hi"})
    assert adapter.verify_webhook_body(raw, {}) is False


def test_a_body_signed_with_the_wrong_secret_is_refused(adapter):
    payload = {"user_id": "u-42", "text": "hi"}
    raw = json.dumps(payload).encode("utf-8")
    headers = {"x-buzz-signature": sign_body(raw, "not-the-secret")}
    assert adapter.verify_webhook_body(raw, headers) is False


def test_a_tampered_body_is_refused(adapter):
    _, headers, _ = body_and_headers({"user_id": "u-42", "text": "hi"})
    tampered = json.dumps({"user_id": "someone-else", "text": "hi"}).encode()
    assert adapter.verify_webhook_body(tampered, headers) is False


def test_the_signature_header_is_matched_case_insensitively(adapter):
    payload, _, raw = body_and_headers({"user_id": "u-42", "text": "hi"})
    headers = {"X-Buzz-Signature": sign_body(raw, SECRET)}
    assert adapter.verify_webhook_body(raw, headers) is True


def test_an_adapter_with_no_secret_refuses_everything(adapter):
    # Fail closed. An empty secret must never mean "accept anything", which is
    # what a plain equality check on two empty strings would have given.
    blind = BuzzAdapter(secret="")
    _, headers, raw = body_and_headers({"user_id": "u-42", "text": "hi"})
    assert blind.verify_webhook_body(raw, headers) is False
    assert blind.verify_webhook_body(raw, {}) is False


def test_a_valid_payload_parses_to_a_dm_event(adapter):
    event = adapter.parse_inbound(
        {"user_id": "u-42", "user_name": "Ralph", "text": "what is on today",
         "conversation_id": "c-7"}, {})
    assert event.text == "what is on today"
    assert event.message_type is MessageType.TEXT
    assert event.source.platform == "buzz"
    assert event.source.user_id == "u-42"
    assert event.source.user_name == "Ralph"
    assert event.source.chat_id == "c-7"
    assert event.source.chat_type == "dm"


def test_a_missing_conversation_falls_back_to_the_user(adapter):
    # One conversation per person is the sane default. Without this the chat
    # id would be empty and every user would share one session row.
    event = adapter.parse_inbound({"user_id": "u-42", "text": "hi"}, {})
    assert event.source.chat_id == "u-42"


@pytest.mark.parametrize("payload", [
    {"text": "hi"},                                  # no user
    {"user_id": "", "text": "hi"},                   # empty user
    {"user_id": "u-42"},                             # no text
    {"user_id": "u-42", "text": "   "},              # blank text
    {"user_id": 42, "text": "hi"},                   # user not a string
    {"user_id": "u-42", "text": 5},                  # text not a string
    {},
    None,
])
def test_an_unusable_payload_parses_to_nothing(adapter, payload):
    assert adapter.parse_inbound(payload, {}) is None


def test_a_user_id_longer_than_the_cap_is_refused(adapter):
    # The id becomes a database key on the pairing path, which is reachable
    # from the public internet. Bound it here rather than at the far end.
    assert adapter.parse_inbound({"user_id": "u" * 200, "text": "hi"}, {}) is None


async def test_send_returns_nothing(adapter):
    # Request and response, like the terminal, not push. A buffer on the
    # adapter would be wrong: the registry caches one adapter per platform, so
    # two concurrent requests would read each other's replies.
    assert await adapter.send("c-7", "anything") is None


async def test_connect_needs_no_registration(adapter):
    assert await adapter.connect() is True
    assert await adapter.disconnect() is None


def test_signing_is_hmac_sha256_hex_with_a_prefix():
    # Pinned so the spec handed to Buzz and this code cannot drift. If this
    # changes, their side breaks silently at the signature check.
    raw = b'{"hello":"world"}'
    expected = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert sign_body(raw, SECRET) == "sha256=" + expected
