"""TasksClient — wraps tasks:8210 HTTP API for webhook-handler dispatchers."""
import pytest
import respx
from httpx import Response

from clients.tasks import TasksClient, TasksAPIError


BASE = "http://tasks-test:8210"


@pytest.fixture
def client():
    return TasksClient(base_url=BASE)


@pytest.mark.asyncio
async def test_list_schedules_sends_only_user_email(client):
    """Critical: TasksClient must NEVER send X-Cron-Secret. Sending both
    headers flips routes_schedules._resolve_caller to operator mode and
    list_schedules returns ALL users' schedules."""
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/schedules").mock(return_value=Response(200, json=[]))
        await client.list_schedules("alice@x.com")
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_list_schedules_returns_payload(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/schedules").mock(return_value=Response(200, json=[
            {"id": "s1", "name": "morning", "cron_expr": "0 8 * * *", "enabled": True},
        ]))
        result = await client.list_schedules("alice@x.com")
        assert len(result) == 1
        assert result[0]["id"] == "s1"


@pytest.mark.asyncio
async def test_create_schedule_201(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/schedules").mock(return_value=Response(201, json={"id": "new-id"}))
        result = await client.create_schedule(
            "alice@x.com", "test", "0 8 * * *", "summarize emails"
        )
        assert result["id"] == "new-id"


@pytest.mark.asyncio
async def test_create_schedule_400_raises(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/schedules").mock(return_value=Response(400, json={"detail": "invalid cron_expr"}))
        with pytest.raises(TasksAPIError) as exc:
            await client.create_schedule("alice@x.com", "test", "bad", "prompt")
        assert exc.value.status == 400
        assert "invalid cron_expr" in exc.value.message


@pytest.mark.asyncio
async def test_delete_schedule_404_raises(client):
    with respx.mock(base_url=BASE) as mock:
        mock.delete("/schedules/abc").mock(return_value=Response(404, json={"detail": "not found"}))
        with pytest.raises(TasksAPIError) as exc:
            await client.delete_schedule("alice@x.com", "abc")
        assert exc.value.status == 404


@pytest.mark.asyncio
async def test_connect_error_raises(client):
    with respx.mock(base_url=BASE) as mock:
        import httpx
        mock.get("/schedules").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(TasksAPIError) as exc:
            await client.list_schedules("alice@x.com")
        assert exc.value.status == 0  # network-level


@pytest.mark.asyncio
async def test_list_projects_endpoint(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/projects").mock(return_value=Response(200, json=[
            {"slug": "shopping-list", "name": "Shopping List", "role": "owner",
             "published": True, "public_url": "https://shopping-list.ai-ui.coolestdomain.win"}
        ]))
        result = await client.list_projects("alice@x.com")
        assert len(result) == 1
        assert result[0]["slug"] == "shopping-list"
