import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.discord import DiscordClient


@pytest.fixture
def client():
    return DiscordClient(application_id="app1", bot_token="tok1")


@pytest.mark.asyncio
async def test_open_dm_returns_channel_id(client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "dm-123"}
    mock_http = AsyncMock()
    mock_http.post.return_value = resp
    with patch("clients.discord.httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value = mock_http
        dm_id = await client.open_dm("user-9")
    assert dm_id == "dm-123"
    args, kwargs = mock_http.post.call_args
    assert "/users/@me/channels" in args[0]
    assert kwargs["json"] == {"recipient_id": "user-9"}


@pytest.mark.asyncio
async def test_open_dm_returns_none_on_error(client):
    resp = MagicMock()
    resp.status_code = 403
    resp.text = "forbidden"
    mock_http = AsyncMock()
    mock_http.post.return_value = resp
    with patch("clients.discord.httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value = mock_http
        assert await client.open_dm("user-9") is None


@pytest.mark.asyncio
async def test_send_dm_opens_then_posts(client):
    with patch.object(client, "open_dm", AsyncMock(return_value="dm-1")), \
         patch.object(client, "post_channel_message", AsyncMock(return_value=True)) as pcm:
        ok = await client.send_dm("user-9", content="hello", components=[{"x": 1}])
    assert ok is True
    pcm.assert_awaited_once_with("dm-1", content="hello", components=[{"x": 1}])


@pytest.mark.asyncio
async def test_send_dm_fails_soft_when_dm_cannot_open(client):
    with patch.object(client, "open_dm", AsyncMock(return_value=None)):
        assert await client.send_dm("user-9", content="hi") is False
