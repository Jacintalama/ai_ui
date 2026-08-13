"""The Buzz endpoint.

Public and unauthenticated at the network level: Caddy sends /webhook/*
straight here, past api-gateway. The shared-secret signature is the whole
door, so the failure modes below are the security surface of this channel.

Unlike Telegram there is no re-delivery to defend against, because we wrote
this contract: a bad signature is told so with a 401 rather than swallowed as
a 200, since the caller is a service we can expect to fix its signing.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
from gateway.platforms.buzz import BuzzAdapter, sign_body

SECRET = "shared-secret-for-the-route-tests"


@pytest.fixture
def adapter():
    a = BuzzAdapter(secret=SECRET)
    a.name = "buzz"
    a.max_message_length = 0
    return a


@pytest.fixture
def client(monkeypatch, adapter):
    monkeypatch.setattr(main.gateway_registry, "adapter",
                        lambda name: adapter if name == "buzz" else None)

    async def fake_handle(event, adapter_):
        return "you said: " + event.text

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)
    main._BUZZ_PER_USER._hits.clear()
    return TestClient(main.app)


def post(client, payload, secret=SECRET, header=True):
    raw = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if header:
        headers["X-Buzz-Signature"] = sign_body(raw, secret)
    return client.post("/webhook/gateway/buzz", content=raw, headers=headers)


def test_a_signed_message_gets_its_reply_inline(client):
    resp = post(client, {"user_id": "u-1", "text": "hello"})
    assert resp.status_code == 200
    assert resp.json() == {"reply": "you said: hello"}


def test_an_unsigned_request_is_refused(client):
    resp = post(client, {"user_id": "u-1", "text": "hello"}, header=False)
    assert resp.status_code == 401


def test_a_wrongly_signed_request_is_refused(client):
    resp = post(client, {"user_id": "u-1", "text": "hello"}, secret="wrong")
    assert resp.status_code == 401


def test_a_bad_signature_never_reaches_the_pipeline(client, monkeypatch):
    seen = []

    async def counting(event, adapter_):
        seen.append(event.text)
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", counting)
    post(client, {"user_id": "u-1", "text": "hello"}, secret="wrong")
    assert seen == []


def test_a_signed_but_unusable_body_is_a_400(client):
    resp = post(client, {"user_id": "u-1"})          # no text
    assert resp.status_code == 400


def test_invalid_json_is_a_400_not_a_traceback(client):
    raw = b"{not json"
    resp = client.post("/webhook/gateway/buzz", content=raw, headers={
        "Content-Type": "application/json",
        "X-Buzz-Signature": sign_body(raw, SECRET),
    })
    assert resp.status_code == 400


def test_the_channel_is_503_when_it_is_not_configured(monkeypatch):
    # Dormant by default: no shared secret on this server means the registry
    # hands out no adapter, and the endpoint must say so rather than accept.
    monkeypatch.setattr(main.gateway_registry, "adapter", lambda name: None)
    c = TestClient(main.app)
    raw = json.dumps({"user_id": "u-1", "text": "hi"}).encode()
    resp = c.post("/webhook/gateway/buzz", content=raw, headers={
        "X-Buzz-Signature": sign_body(raw, SECRET)})
    assert resp.status_code == 503


def test_one_user_flooding_is_refused(client):
    codes = [post(client, {"user_id": "u-loud", "text": f"m{i}"}).status_code
             for i in range(30)]
    assert 429 in codes
    assert codes[0] == 200


def test_one_flooder_does_not_lock_out_another_user(client):
    # Keyed on the Buzz user, NOT on the caller address: every request comes
    # from Buzz's own servers, so an address key would be one bucket for their
    # entire user base.
    for i in range(30):
        post(client, {"user_id": "u-loud", "text": f"m{i}"})
    assert post(client, {"user_id": "u-quiet", "text": "hello"}).status_code == 200


def test_the_signature_covers_the_exact_bytes_sent(client):
    # Signed over one encoding, sent as another. A server that re-serialised
    # the parsed object before checking would accept this; we must not.
    payload = {"user_id": "u-1", "text": "hello"}
    signed_over = json.dumps(payload, separators=(",", ":")).encode()
    sent = json.dumps(payload, indent=2).encode()
    resp = client.post("/webhook/gateway/buzz", content=sent, headers={
        "Content-Type": "application/json",
        "X-Buzz-Signature": sign_body(signed_over, SECRET),
    })
    assert resp.status_code == 401
