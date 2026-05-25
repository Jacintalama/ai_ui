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
        route = mock.post("/schedules").mock(return_value=Response(201, json={"id": "new-id"}))
        result = await client.create_schedule(
            "alice@x.com", "test", "0 8 * * *", "summarize emails"
        )
        assert result["id"] == "new-id"
        import json
        sent = json.loads(route.calls.last.request.content)
        assert sent == {
            "name": "test",
            "cron_expr": "0 8 * * *",
            "prompt": "summarize emails",
            "tz": "Asia/Manila",
        }


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


@pytest.mark.asyncio
async def test_get_project_status_endpoint(client):
    """Confirms the slug path is built correctly and the user-email header is sent."""
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/projects/shopping/status").mock(
            return_value=Response(200, json={
                "slug": "shopping", "name": "Shopping", "role": "owner",
                "published": True,
                "public_url": "https://shopping.ai-ui.coolestdomain.win",
                "last_commit_at": None, "last_commit_message": None,
                "custom_domain": None,
            })
        )
        result = await client.get_project_status("alice@x.com", "shopping")
        assert result["slug"] == "shopping"
        assert result["published"] is True
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_start_build_sends_only_user_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/build").mock(
            return_value=Response(201, json={
                "task_id": "t1", "slug": "todo-a1b2", "status": "running"})
        )
        result = await client.start_build("alice@x.com", "a todo app")
        assert result["slug"] == "todo-a1b2"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}
        import json
        assert json.loads(req.content) == {
            "description": "a todo app", "name": None, "template_key": None}


@pytest.mark.asyncio
async def test_start_build_429_raises(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/aiuibuilder/build").mock(
            return_value=Response(429, json={"detail": "A build is already running"}))
        with pytest.raises(TasksAPIError) as exc:
            await client.start_build("alice@x.com", "another app")
        assert exc.value.status == 429


@pytest.mark.asyncio
async def test_start_build_includes_template_key(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/build").mock(
            return_value=Response(201, json={"task_id": "t", "slug": "s", "status": "running"}))
        await client.start_build("a@x.com", "a designer site", template_key="portfolio")
        import json
        sent = json.loads(route.calls.last.request.content)
        assert sent["template_key"] == "portfolio"
        assert sent["description"] == "a designer site"


@pytest.mark.asyncio
async def test_list_templates_sends_only_user_email(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/aiuibuilder/templates").mock(
            return_value=Response(200, json=[{"key": "portfolio", "label": "Portfolio",
                "emoji": "🎨", "description": "personal showcase", "has_app": True, "note": ""}]))
        result = await client.list_templates("a@x.com")
        assert result[0]["key"] == "portfolio"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "a@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_get_build_status_endpoint(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/aiuibuilder/build/t1").mock(
            return_value=Response(200, json={
                "status": "completed", "slug": "todo-a1b2",
                "preview_url": "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/",
                "error": None}))
        result = await client.get_build_status("alice@x.com", "t1")
        assert result["status"] == "completed"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_publish_app_posts_and_returns_status(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/portfolio-ab12/publish").mock(
            return_value=Response(200, json={
                "published": True,
                "public_url": "https://portfolio-ab12.ai-ui.coolestdomain.win/",
            })
        )
        out = await client.publish_app("alice@x.com", "portfolio-ab12")
    assert route.called
    req = route.calls.last.request
    assert req.headers.get("x-user-email") == "alice@x.com"
    assert "x-cron-secret" not in {k.lower() for k in req.headers}
    assert out["public_url"] == "https://portfolio-ab12.ai-ui.coolestdomain.win/"


@pytest.mark.asyncio
async def test_unpublish_app_deletes(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.delete("/api/aiuibuilder/slug-1/publish").mock(return_value=Response(204))
        ok = await client.unpublish_app("alice@x.com", "slug-1")
    assert ok is True
    req = route.calls.last.request
    assert req.headers.get("x-user-email") == "alice@x.com"
    assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_enhance_app_posts(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/slug-1/enhance").mock(
            return_value=Response(201, json={"task_id": "t1", "slug": "slug-1", "status": "running"})
        )
        out = await client.enhance_app("alice@x.com", "slug-1", "make header green")
    assert out["task_id"] == "t1"
    req = route.calls.last.request
    assert req.headers.get("x-user-email") == "alice@x.com"
    assert "x-cron-secret" not in {k.lower() for k in req.headers}
    import json as _j
    assert _j.loads(req.content)["prompt"] == "make header green"


@pytest.mark.asyncio
async def test_create_schedule_includes_delivery_channel_id(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/schedules").mock(return_value=Response(201, json={"id": "x"}))
        await client.create_schedule(
            "alice@x.com", "test", "0 8 * * *", "summarize emails",
            delivery_channel_id="123456",
        )
        import json
        sent = json.loads(route.calls.last.request.content)
        assert sent["delivery_channel_id"] == "123456"
        assert sent["name"] == "test"


@pytest.mark.asyncio
async def test_create_schedule_omits_delivery_channel_when_none(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/schedules").mock(return_value=Response(201, json={"id": "x"}))
        await client.create_schedule("alice@x.com", "t", "0 8 * * *", "p")
        import json
        sent = json.loads(route.calls.last.request.content)
        assert "delivery_channel_id" not in sent


@pytest.mark.asyncio
async def test_pause_schedule_posts_disable(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/schedules/sid1/disable").mock(
            return_value=Response(200, json={"status": "disabled"}))
        ok = await client.pause_schedule("alice@x.com", "sid1")
        assert ok is True
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_resume_schedule_posts_enable(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/schedules/sid1/enable").mock(
            return_value=Response(200, json={"status": "enabled"}))
        assert await client.resume_schedule("alice@x.com", "sid1") is True


@pytest.mark.asyncio
async def test_run_schedule_now_posts_run_now(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/schedules/sid1/run-now").mock(
            return_value=Response(200, json={"status": "dispatched"}))
        assert await client.run_schedule_now("alice@x.com", "sid1") is True
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
