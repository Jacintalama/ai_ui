"""Every internal gateway endpoint must fail closed without the secret.

These endpoints mint tokens that act as any user, so an unset or mismatched
INTERNAL_CALLBACK_SECRET must be a 403, never an open door.
"""
import os

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import routes_gateway


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    return TestClient(app, raise_server_exceptions=False)


CALLS = [
    ("post", "/gateway/resolve", {"platform": "telegram", "platform_user_id": "1"}),
    ("get", "/gateway/session?platform=telegram&chat_id=1", None),
    ("put", "/gateway/session", {"platform": "telegram", "chat_id": "1",
                                 "owui_chat_id": "c", "owui_user_id": "u"}),
    ("get", "/gateway/sessions/recent?owui_user_id=u", None),
]


@pytest.mark.parametrize("method,path,body", CALLS)
def test_missing_secret_is_403(client, method, path, body):
    resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert resp.status_code == 403


@pytest.mark.parametrize("method,path,body", CALLS)
def test_wrong_secret_is_403(client, method, path, body):
    headers = {"X-Internal-Secret": "not-the-secret"}
    resp = (getattr(client, method)(path, json=body, headers=headers) if body
            else getattr(client, method)(path, headers=headers))
    assert resp.status_code == 403


def test_an_unset_server_secret_still_refuses(client, monkeypatch):
    # An empty expected secret must not mean "everything matches".
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "")
    resp = client.post("/gateway/resolve", json={"platform": "telegram",
                                                 "platform_user_id": "1"},
                       headers={"X-Internal-Secret": ""})
    assert resp.status_code == 403


def test_resolve_refuses_a_blank_platform_user(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "test-internal-secret")
    resp = client.post("/gateway/resolve", json={"platform": "telegram",
                                                 "platform_user_id": ""},
                       headers={"X-Internal-Secret": "test-internal-secret"})
    assert resp.status_code == 422
