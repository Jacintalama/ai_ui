"""DiscordClient.post_channel_message — bot-token channel post (outlives the
15-minute interaction-token window)."""
import pytest
import respx
from httpx import Response

from clients.discord import DiscordClient, DISCORD_API_BASE


@pytest.fixture
def dc():
    return DiscordClient(application_id="app1", bot_token="bot-tok")


@pytest.mark.asyncio
async def test_post_channel_message_uses_bot_token(dc):
    with respx.mock() as mock:
        route = mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
            return_value=Response(200, json={"id": "m1"}))
        ok = await dc.post_channel_message("c1", "hello")
        assert ok is True
        req = route.calls.last.request
        assert req.headers.get("authorization") == "Bot bot-tok"
        import json
        assert json.loads(req.content) == {"content": "hello"}


@pytest.mark.asyncio
async def test_post_channel_message_truncates_2000(dc):
    with respx.mock() as mock:
        route = mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
            return_value=Response(200, json={"id": "m1"}))
        await dc.post_channel_message("c1", "x" * 5000)
        import json
        assert len(json.loads(route.calls.last.request.content)["content"]) == 2000


@pytest.mark.asyncio
async def test_post_channel_message_returns_false_on_error(dc):
    with respx.mock() as mock:
        mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
            return_value=Response(403, json={"message": "no perms"}))
        assert await dc.post_channel_message("c1", "hi") is False
