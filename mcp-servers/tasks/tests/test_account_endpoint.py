"""The endpoint the assistant's tool calls.

Internal only, like every other endpoint that acts for a named user.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routes_account as ra


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(ra, "_require_internal", lambda s: None)
    monkeypatch.setattr(ra, "summarise", AsyncMock(return_value={
        "connected": [{"id": "gmail", "label": "Gmail"}],
        "not_connected": [{"id": "clickup", "label": "ClickUp", "how": "key",
                           "connect_url": "#aiui-connect:clickup",
                           "where": "ClickUp, under Settings then Apps"}]}))


async def test_it_returns_the_summary_for_the_named_user():
    out = await ra.summary(user_email="owner@example.com", x_internal_secret="s")
    assert out["connected"][0]["id"] == "gmail"
    assert out["not_connected"][0]["id"] == "clickup"
    assert ra.summarise.await_args.args[0] == "owner@example.com"


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")
    monkeypatch.setattr(ra, "_require_internal", deny)
    with pytest.raises(HTTPException) as caught:
        await ra.summary(user_email="o@e.com", x_internal_secret="wrong")
    assert caught.value.status_code == 403


async def test_the_secret_is_checked_before_any_work(monkeypatch):
    """An unauthenticated caller must not be able to make us read a
    database, even if the answer is then thrown away."""
    calls = []
    monkeypatch.setattr(ra, "summarise",
                        AsyncMock(side_effect=lambda e: calls.append(e)))

    def deny(secret):
        raise HTTPException(status_code=403, detail="nope")
    monkeypatch.setattr(ra, "_require_internal", deny)

    with pytest.raises(HTTPException):
        await ra.summary(user_email="o@e.com", x_internal_secret="wrong")
    assert calls == [], "work happened before the secret was checked"
