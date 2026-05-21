"""DiscordClient private-thread helpers."""
import httpx
import pytest
import respx

from clients.discord import DiscordClient, DISCORD_API_BASE


def _client():
    return DiscordClient(application_id="app-1", bot_token="bot-tok")


@pytest.mark.asyncio
async def test_create_private_thread_returns_id():
    c = _client()
    with respx.mock:
        route = respx.post(f"{DISCORD_API_BASE}/channels/chan-1/threads").mock(
            return_value=httpx.Response(201, json={"id": "thread-9"})
        )
        tid = await c.create_private_thread("chan-1", "portfolio-ralph")
    assert tid == "thread-9"
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bot bot-tok"
    import json as _j
    body = _j.loads(req.content)
    assert body["type"] == 12
    assert body["name"] == "portfolio-ralph"
    assert body["invitable"] is False
    assert body["auto_archive_duration"] == 1440


@pytest.mark.asyncio
async def test_create_private_thread_none_on_error():
    c = _client()
    with respx.mock:
        respx.post(f"{DISCORD_API_BASE}/channels/chan-1/threads").mock(
            return_value=httpx.Response(403, json={"message": "Missing Permissions"})
        )
        tid = await c.create_private_thread("chan-1", "x")
    assert tid is None


@pytest.mark.asyncio
async def test_add_thread_member_true_on_204():
    c = _client()
    with respx.mock:
        route = respx.put(
            f"{DISCORD_API_BASE}/channels/thread-9/thread-members/user-7"
        ).mock(return_value=httpx.Response(204))
        ok = await c.add_thread_member("thread-9", "user-7")
    assert ok is True
    assert route.calls.last.request.headers["authorization"] == "Bot bot-tok"


@pytest.mark.asyncio
async def test_add_thread_member_false_on_error():
    c = _client()
    with respx.mock:
        respx.put(
            f"{DISCORD_API_BASE}/channels/thread-9/thread-members/user-7"
        ).mock(return_value=httpx.Response(403))
        ok = await c.add_thread_member("thread-9", "user-7")
    assert ok is False
