"""Unit tests for io_mcp_scheduler — create / list / delete tool handlers."""
import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_scheduler.tools import (
    create_schedule_tool_spec,
    list_schedules_tool_spec,
    delete_schedule_tool_spec,
    make_create_handler,
    make_list_handler,
    make_delete_handler,
)


# --- create -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_posts_to_api_tasks_schedules():
    client = AsyncMock()
    client.post = AsyncMock(return_value={"id": "abc-123"})
    handler = make_create_handler(client)
    result = await handler({
        "name": "morning-stocks",
        "cron_expr": "0 8 * * *",
        "prompt": "watch AAPL",
    })
    client.post.assert_called_once_with(
        "/api/tasks/schedules",
        json={
            "name": "morning-stocks",
            "cron_expr": "0 8 * * *",
            "tz": "Asia/Manila",  # default tz applied
            "persona": "",
            "prompt": "watch AAPL",
            "enabled": True,
        },
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["id"] == "abc-123"
    assert "morning-stocks" in body["data"]["summary"]


@pytest.mark.asyncio
async def test_create_respects_explicit_tz_and_persona():
    client = AsyncMock()
    client.post = AsyncMock(return_value={"id": "abc-456"})
    handler = make_create_handler(client)
    await handler({
        "name": "europe-meeting",
        "cron_expr": "0 9 * * 1",
        "tz": "Europe/London",
        "persona": "You are my exec assistant.",
        "prompt": "remind team of Monday standup",
    })
    sent = client.post.call_args.kwargs["json"]
    assert sent["tz"] == "Europe/London"
    assert sent["persona"] == "You are my exec assistant."


# --- list -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_returns_trimmed_schedule_view():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[
        {
            "id": "id-1", "name": "stocks", "cron_expr": "0 8 * * *",
            "tz": "Asia/Manila", "enabled": True,
            "last_run_at": "2026-05-18T08:00:00+00:00",
            "last_run_status": "completed",
            "persona": "huge wall of text", "prompt": "huge wall of text",
            "user_email": "alice@x.com",
        },
    ])
    handler = make_list_handler(client)
    result = await handler({})
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["count"] == 1
    # Trimmed view — no prompt / persona / user_email leakage
    item = body["data"]["schedules"][0]
    assert "prompt" not in item
    assert "persona" not in item
    assert item["id"] == "id-1"
    assert item["last_run_status"] == "completed"


# --- delete -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_calls_correct_path():
    client = AsyncMock()
    client.delete = AsyncMock(return_value={"status": "deleted"})
    handler = make_delete_handler(client)
    result = await handler({"schedule_id": "uuid-abc"})
    client.delete.assert_called_once_with("/api/tasks/schedules/uuid-abc")
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert "uuid-abc" in body["data"]["summary"]


# --- tool specs -------------------------------------------------------------

def test_create_spec_shape():
    t = create_schedule_tool_spec()
    assert t.name == "create_schedule"
    required = t.inputSchema["required"]
    assert "name" in required
    assert "cron_expr" in required
    assert "prompt" in required


def test_list_spec_shape():
    t = list_schedules_tool_spec()
    assert t.name == "list_my_schedules"


def test_delete_spec_shape():
    t = delete_schedule_tool_spec()
    assert t.name == "delete_schedule"
    assert "schedule_id" in t.inputSchema["required"]
