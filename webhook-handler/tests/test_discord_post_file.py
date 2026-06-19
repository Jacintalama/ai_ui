"""Tests for DiscordClient.post_channel_file (multipart file upload)."""
import json
import pytest
from clients.discord import DiscordClient


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.text = ""


class FakeAsyncClient:
    """Fake httpx.AsyncClient that captures post() arguments."""

    def __init__(self, status_code: int = 200):
        self._status_code = status_code
        self.captured = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, *, headers=None, data=None, files=None, **kwargs):
        self.captured["url"] = url
        self.captured["headers"] = headers or {}
        self.captured["data"] = data or {}
        self.captured["files"] = files or {}
        return FakeResponse(self._status_code)


@pytest.fixture
def client():
    return DiscordClient(application_id="app", bot_token="tok")


@pytest.mark.asyncio
async def test_returns_true_on_200(client, monkeypatch):
    fake = FakeAsyncClient(status_code=200)
    monkeypatch.setattr("clients.discord.httpx.AsyncClient", lambda **kw: fake)

    result = await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
    )
    assert result is True


@pytest.mark.asyncio
async def test_authorization_header_bot_tok(client, monkeypatch):
    fake = FakeAsyncClient(status_code=200)
    monkeypatch.setattr("clients.discord.httpx.AsyncClient", lambda **kw: fake)

    await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
    )
    assert fake.captured["headers"]["Authorization"] == "Bot tok"


@pytest.mark.asyncio
async def test_no_content_type_header(client, monkeypatch):
    fake = FakeAsyncClient(status_code=200)
    monkeypatch.setattr("clients.discord.httpx.AsyncClient", lambda **kw: fake)

    await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
    )
    assert "Content-Type" not in fake.captured["headers"]


@pytest.mark.asyncio
async def test_payload_json_attachments(client, monkeypatch):
    fake = FakeAsyncClient(status_code=200)
    monkeypatch.setattr("clients.discord.httpx.AsyncClient", lambda **kw: fake)

    await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
        content="Here is your video",
    )
    payload = json.loads(fake.captured["data"]["payload_json"])
    assert payload["attachments"] == [{"id": 0, "filename": "out.mp4"}]


@pytest.mark.asyncio
async def test_files_key_present(client, monkeypatch):
    fake = FakeAsyncClient(status_code=200)
    monkeypatch.setattr("clients.discord.httpx.AsyncClient", lambda **kw: fake)

    await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
    )
    assert "files[0]" in fake.captured["files"]


@pytest.mark.asyncio
async def test_returns_false_on_error_status(client, monkeypatch):
    fake = FakeAsyncClient(status_code=400)
    monkeypatch.setattr("clients.discord.httpx.AsyncClient", lambda **kw: fake)

    result = await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
    )
    assert result is False


@pytest.mark.asyncio
async def test_returns_false_on_exception(client, monkeypatch):
    def raise_exc(**kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("clients.discord.httpx.AsyncClient", raise_exc)

    result = await client.post_channel_file(
        channel_id="ch1",
        files=[("out.mp4", b"data", "video/mp4")],
    )
    assert result is False
