"""Fetching a user's bot config over the internal seam.

An unknown key must come back as None rather than raising, because an inbound
update on a deleted bot is normal and must not page anyone.
"""
import pytest

from clients.tasks import TasksAPIError, TasksClient


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def client(monkeypatch):
    c = TasksClient("http://tasks:8210", internal_secret="s")
    return c


async def test_a_known_key_returns_the_config(client, monkeypatch):
    async def _req(method, path, **kw):
        assert method == "GET"
        assert path == "/gateway/bots/abc123"
        return FakeResponse(200, {"owner_email": "ralph@example.com",
                                  "token": "111:AAH", "enabled": True})
    monkeypatch.setattr(client, "_internal_request", _req)
    config = await client.gateway_bot_config("abc123")
    assert config["owner_email"] == "ralph@example.com"


async def test_an_unknown_key_is_none_not_an_error(client, monkeypatch):
    async def _req(method, path, **kw):
        raise TasksAPIError(404, "unknown bot")
    monkeypatch.setattr(client, "_internal_request", _req)
    assert await client.gateway_bot_config("nope") is None


async def test_tasks_being_down_still_raises(client, monkeypatch):
    # The caller must be able to tell "no such bot" from "I could not ask",
    # because the second one has to become a 503 so Telegram redelivers.
    async def _req(method, path, **kw):
        raise TasksAPIError(503, "down")
    monkeypatch.setattr(client, "_internal_request", _req)
    with pytest.raises(TasksAPIError):
        await client.gateway_bot_config("abc123")


async def test_claiming_reports_whether_it_took(client, monkeypatch):
    async def _req(method, path, **kw):
        assert path == "/gateway/bots/abc123/claim"
        assert kw["json"] == {"platform_user_id": "999"}
        return FakeResponse(200, {"claimed": True})
    monkeypatch.setattr(client, "_internal_request", _req)
    assert await client.gateway_bot_claim("abc123", "999") is True
