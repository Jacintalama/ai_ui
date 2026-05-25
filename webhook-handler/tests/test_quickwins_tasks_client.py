"""TasksClient additions: update_schedule (user-scoped) + link methods
(system calls authed with X-Internal-Secret, NOT X-User-Email)."""
import json

import pytest
import respx
from httpx import Response

from clients.tasks import TasksClient

BASE = "http://tasks-test:8210"


@pytest.fixture
def client():
    return TasksClient(base_url=BASE, internal_secret="sek")


@pytest.mark.asyncio
async def test_update_schedule_patches_with_user_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.patch("/schedules/sid1").mock(return_value=Response(200, json={"id": "sid1"}))
        await client.update_schedule("a@x.com", "sid1", name="n", cron="0 8 * * *", prompt="p")
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "a@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}
        assert json.loads(req.content) == {"name": "n", "cron_expr": "0 8 * * *", "prompt": "p"}


@pytest.mark.asyncio
async def test_request_link_uses_internal_secret_not_user_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/discord-links/request").mock(
            return_value=Response(200, json={"status": "pending"}))
        out = await client.request_link("123", "alice", "alice@x.com")
        assert out["status"] == "pending"
        req = route.calls.last.request
        assert req.headers.get("x-internal-secret") == "sek"
        assert "x-user-email" not in {k.lower() for k in req.headers}
        assert json.loads(req.content) == {
            "discord_id": "123", "discord_username": "alice", "email": "alice@x.com"}


@pytest.mark.asyncio
async def test_approve_link_returns_email(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/discord-links/123/approve").mock(
            return_value=Response(200, json={"email": "alice@x.com"}))
        out = await client.approve_link("123", decided_by="admin@x.com")
        assert out["email"] == "alice@x.com"


@pytest.mark.asyncio
async def test_reject_link(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/discord-links/123/reject").mock(
            return_value=Response(200, json={"status": "rejected"}))
        assert await client.reject_link("123") is True


@pytest.mark.asyncio
async def test_resolve_link_approved_returns_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/discord-links/resolve/123").mock(
            return_value=Response(200, json={"email": "alice@x.com"}))
        assert await client.resolve_link("123") == "alice@x.com"
        assert route.calls.last.request.headers.get("x-internal-secret") == "sek"


@pytest.mark.asyncio
async def test_resolve_link_not_linked_returns_none(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/discord-links/resolve/999").mock(
            return_value=Response(200, json={"email": None}))
        assert await client.resolve_link("999") is None
