"""The bot reads Channels and Graph from the tasks service as the user.

Both routes are owner-scoped by the email the bot sends, so the security
invariant of TasksClient matters more here than usual: ONLY X-User-Email, never
X-User-Admin (which the tasks service would honour) and never X-Internal-Secret.
The paths are the public mounts, the same ones the browser hits through the
api-gateway, so what the bot shows is exactly what the web page shows.
"""
import pytest
import respx
from httpx import Response

from clients.tasks import TasksAPIError, TasksClient

BASE = "http://tasks-test:8210"
EMAIL = "me@example.com"


def _client():
    return TasksClient(base_url=BASE, internal_secret="never-sent")


def _only_user_email(request):
    assert request.headers["X-User-Email"] == EMAIL
    assert "x-user-admin" not in {k.lower() for k in request.headers}
    assert "x-internal-secret" not in {k.lower() for k in request.headers}


@pytest.mark.asyncio
async def test_channel_connections_is_the_public_gateway_page_route():
    with respx.mock() as mock:
        route = mock.get(f"{BASE}/tasks/gateway/connections").mock(
            return_value=Response(200, json={"telegram_bot": "@io", "connections": []}))
        data = await _client().get_channel_connections(EMAIL)
    assert route.called
    _only_user_email(route.calls.last.request)
    assert data == {"telegram_bot": "@io", "connections": []}


@pytest.mark.asyncio
async def test_knowledge_graph_is_the_public_mine_route():
    with respx.mock() as mock:
        route = mock.get(f"{BASE}/api/tasks/graph/mine").mock(
            return_value=Response(200, json={"count": 3, "counts": {"topic": 3}}))
        data = await _client().get_knowledge_graph(EMAIL)
    assert route.called
    _only_user_email(route.calls.last.request)
    assert data["count"] == 3


@pytest.mark.asyncio
async def test_graph_context_sends_the_query_as_q():
    with respx.mock() as mock:
        route = mock.get(f"{BASE}/api/tasks/graph/mine/context").mock(
            return_value=Response(200, json={"context": "x", "count": 1, "used": True}))
        data = await _client().get_graph_context(EMAIL, "my portfolio")
    assert route.called
    req = route.calls.last.request
    _only_user_email(req)
    assert req.url.params["q"] == "my portfolio"
    assert data["used"] is True


@pytest.mark.asyncio
async def test_an_error_surfaces_as_tasks_api_error_with_the_detail():
    with respx.mock() as mock:
        mock.get(f"{BASE}/api/tasks/graph/mine").mock(
            return_value=Response(403, json={"detail": "Sign in to use tools."}))
        with pytest.raises(TasksAPIError) as e:
            await _client().get_knowledge_graph(EMAIL)
    assert e.value.status == 403
    assert "Sign in" in str(e.value)
