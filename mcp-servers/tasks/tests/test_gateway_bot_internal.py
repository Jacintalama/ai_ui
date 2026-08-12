"""The lookup webhook-handler makes on a cold cache.

This endpoint hands out a decrypted bot token, so the only thing standing
between it and the internet is the internal secret and the fact that it is
mounted bare. Both are asserted here.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")
os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway

HEADERS = {"X-Internal-Secret": "test-internal-secret"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    return TestClient(app, raise_server_exceptions=False)


def test_lookup_without_the_secret_is_403(client):
    assert client.get("/gateway/bots/abc").status_code == 403


def test_claim_without_the_secret_is_403(client):
    resp = client.post("/gateway/bots/abc/claim", json={"platform_user_id": "1"})
    assert resp.status_code == 403


def test_the_lookup_is_not_on_the_browser_router(client):
    # page_router carries X-User-Email from a browser session. A bot token
    # endpoint must never be reachable that way. Either 404 (route doesn't exist)
    # or 405 (route exists but method not allowed) both satisfy this requirement.
    app = FastAPI()
    app.include_router(routes_gateway.page_router)
    browser = TestClient(app, raise_server_exceptions=False)
    status = browser.get("/tasks/gateway/bots/abc").status_code
    assert status in (404, 405), f"Expected 404 or 405, got {status}"
