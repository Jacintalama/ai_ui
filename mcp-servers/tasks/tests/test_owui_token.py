"""mint_owui_token must produce a token Open WebUI's own decoder accepts.

Open WebUI signs session JWTs HS256 over WEBUI_SECRET_KEY and its
is_valid_token is a revocation blocklist, so a fresh token with a random jti
passes. These tests pin the wire format; the real proof that Open WebUI
accepts it is the server check in step 6, which no unit test can replace.
"""
import base64
import hashlib
import hmac
import json

import pytest

import owui_token


def _decode(token: str) -> tuple[dict, dict, bytes, bytes]:
    header_b64, payload_b64, sig_b64 = token.split(".")

    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    signing_input = f"{header_b64}.{payload_b64}".encode()
    return (
        json.loads(unb64(header_b64)),
        json.loads(unb64(payload_b64)),
        unb64(sig_b64),
        signing_input,
    )


def test_mint_produces_three_part_hs256_token(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    token = owui_token.mint_owui_token("user-abc")

    header, payload, sig, signing_input = _decode(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["id"] == "user-abc"
    assert payload["exp"] - payload["iat"] == 60
    assert payload["jti"]

    expected = hmac.new(b"test-secret", signing_input, hashlib.sha256).digest()
    assert hmac.compare_digest(sig, expected)


def test_each_mint_has_a_distinct_jti(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    a = _decode(owui_token.mint_owui_token("user-abc"))[1]
    b = _decode(owui_token.mint_owui_token("user-abc"))[1]
    assert a["jti"] != b["jti"]


def test_ttl_is_honoured(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    payload = _decode(owui_token.mint_owui_token("user-abc", ttl_seconds=5))[1]
    assert payload["exp"] - payload["iat"] == 5


def test_fails_closed_without_a_secret(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        owui_token.mint_owui_token("user-abc")


def test_rejects_an_empty_user_id(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    with pytest.raises(ValueError):
        owui_token.mint_owui_token("")
