"""DiscordClient: embeds support on post_channel_message + edit_original."""
import json

import pytest
import respx
from httpx import Response

from clients.discord import DiscordClient


@pytest.mark.asyncio
async def test_post_channel_message_includes_embeds():
    d = DiscordClient(application_id="app", bot_token="tok")
    with respx.mock as mock:
        route = mock.post("https://discord.com/api/v10/channels/c1/messages").mock(
            return_value=Response(200, json={}))
        ok = await d.post_channel_message("c1", "", embeds=[{"title": "x", "color": 123}],
                                          components=[{"type": 1, "components": []}])
        assert ok is True
        sent = json.loads(route.calls.last.request.content)
        assert sent["embeds"] == [{"title": "x", "color": 123}]


@pytest.mark.asyncio
async def test_edit_original_includes_embeds():
    d = DiscordClient(application_id="app", bot_token="tok")
    with respx.mock as mock:
        route = mock.patch(
            "https://discord.com/api/v10/webhooks/app/tok123/messages/@original"
        ).mock(return_value=Response(200, json={}))
        ok = await d.edit_original("tok123", "", embeds=[{"title": "y"}])
        assert ok is True
        sent = json.loads(route.calls.last.request.content)
        assert sent["embeds"] == [{"title": "y"}]


@pytest.mark.asyncio
async def test_post_channel_message_no_embeds_omits_key():
    d = DiscordClient(application_id="app", bot_token="tok")
    with respx.mock as mock:
        route = mock.post("https://discord.com/api/v10/channels/c1/messages").mock(
            return_value=Response(200, json={}))
        await d.post_channel_message("c1", "hello")
        sent = json.loads(route.calls.last.request.content)
        assert "embeds" not in sent
        assert sent["content"] == "hello"
