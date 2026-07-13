"""TasksClient.answer_build — resume a paused build via the user-scoped endpoint."""
import json

import pytest
import respx
from httpx import Response

from clients.tasks import TasksClient


BASE = "http://tasks-test:8210"


@pytest.fixture
def client():
    return TasksClient(base_url=BASE)


@pytest.mark.asyncio
async def test_answer_build_posts_answer_and_returns_status(client):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/aiuibuilder/build/t1/answer").mock(
            return_value=Response(200, json={"status": "running", "slug": "s1"})
        )
        result = await client.answer_build("alice@x.com", "t1", "use blue")
        assert result["status"] == "running"
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert json.loads(req.content) == {"answer": "use blue"}
