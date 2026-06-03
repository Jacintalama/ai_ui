"""TasksClient: per-user builder-thread get/set (internal-secret) + delete_app."""
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
async def test_get_user_builder_thread_returns_id(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/discord-links/123/builder-thread").mock(
            return_value=Response(200, json={"thread_id": "t9"}))
        assert await client.get_user_builder_thread("123") == "t9"
        assert route.calls.last.request.headers.get("x-internal-secret") == "sek"
        assert "x-user-email" not in {k.lower() for k in route.calls.last.request.headers}


@pytest.mark.asyncio
async def test_get_user_builder_thread_none(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/discord-links/123/builder-thread").mock(
            return_value=Response(200, json={"thread_id": None}))
        assert await client.get_user_builder_thread("123") is None


@pytest.mark.asyncio
async def test_set_user_builder_thread(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/discord-links/123/builder-thread").mock(
            return_value=Response(200, json={"status": "ok"}))
        assert await client.set_user_builder_thread("123", "t9") is True
        assert json.loads(route.calls.last.request.content) == {"thread_id": "t9"}
        assert route.calls.last.request.headers.get("x-internal-secret") == "sek"


@pytest.mark.asyncio
async def test_delete_app_deletes(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.delete("/api/aiuibuilder/slug-1/app").mock(
            return_value=Response(204))
        ok = await client.delete_app("alice@x.com", "slug-1")
    assert ok is True
    req = route.calls.last.request
    assert req.headers.get("x-user-email") == "alice@x.com"
    assert "x-cron-secret" not in {k.lower() for k in req.headers}
