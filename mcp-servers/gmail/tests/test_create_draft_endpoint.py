"""Offline endpoint test: not-connected path and drafts payload shape.
Sets a dummy Fernet key so main.py imports, and monkeypatches the token
lookup + Gmail HTTP call so no network is used."""
import os
import base64

import pytest
from fastapi.testclient import TestClient

# crypto_utils raises at import unless this is set. Dummy key, never used here.
os.environ.setdefault(
    "AIUI_FERNET_KEY",
    base64.urlsafe_b64encode(b"0" * 32).decode(),
)

import importlib.util
import pathlib

MAIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "main.py"


def _load_main():
    spec = importlib.util.spec_from_file_location("gmail_main", MAIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def main():
    return _load_main()


def test_not_connected_returns_clear_error(main, monkeypatch):
    async def fake_token(_email):
        return None
    monkeypatch.setattr(main, "get_valid_token", fake_token)
    client = TestClient(main.app)
    r = client.post("/gmail_create_draft",
                    json={"to": "a@b.com", "subject": "s", "body": "b"},
                    headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 200
    assert "error" in r.json()


def test_creates_draft_with_message_raw_payload(main, monkeypatch):
    captured = {}

    async def fake_token(_email):
        return "tok"

    async def fake_request(access_token, path, params=None, method="GET", json_body=None):
        captured["path"] = path
        captured["method"] = method
        captured["json_body"] = json_body
        return {"id": "draft123", "message": {"id": "msg1"}}

    monkeypatch.setattr(main, "get_valid_token", fake_token)
    monkeypatch.setattr(main, "gmail_request", fake_request)
    client = TestClient(main.app)
    r = client.post("/gmail_create_draft",
                    json={"to": "a@b.com", "subject": "Hi", "body": "Body"},
                    headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["draft_id"] == "draft123"
    assert captured["path"] == "users/me/drafts"
    assert captured["method"] == "POST"
    # New drafts have no threadId; payload wraps a raw message.
    assert "raw" in captured["json_body"]["message"]
    assert "threadId" not in captured["json_body"]["message"]


def test_invalid_recipient_returns_422(main, monkeypatch):
    async def fake_token(_email):
        return "tok"

    monkeypatch.setattr(main, "get_valid_token", fake_token)
    client = TestClient(main.app)
    r = client.post("/gmail_create_draft",
                    json={"to": "   ", "subject": "s", "body": "b"},
                    headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 422
