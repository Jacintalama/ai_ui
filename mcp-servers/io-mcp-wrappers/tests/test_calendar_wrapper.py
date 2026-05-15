import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_calendar.tools import (
    calendar_list_events_tool_spec,
    calendar_create_event_tool_spec,
    make_calendar_list_events_handler,
    make_calendar_create_event_handler,
)


# --- calendar_list_events ---

@pytest.mark.asyncio
async def test_calendar_list_events_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"events": [{"event_id": "e1", "title": "Standup"}]})
    handler = make_calendar_list_events_handler(client)
    result = await handler({"max_results": 10, "time_min": "2026-05-01T00:00:00"})
    client.post.assert_called_once_with(
        "/calendar/calendar_list_events",
        json={"max_results": 10, "time_min": "2026-05-01T00:00:00"},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["events"][0]["title"] == "Standup"


@pytest.mark.asyncio
async def test_calendar_list_events_defaults(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"events": []})
    handler = make_calendar_list_events_handler(client)
    await handler({})
    client.post.assert_called_once_with(
        "/calendar/calendar_list_events",
        json={"max_results": 25},
    )


@pytest.mark.asyncio
async def test_calendar_list_events_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_calendar_list_events_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({})
    assert ei.value.kind == "auth"


def test_calendar_list_events_tool_spec_shape():
    t = calendar_list_events_tool_spec()
    assert t.name == "calendar_list_events"
    assert "max_results" in t.inputSchema["properties"]


# --- calendar_create_event ---

@pytest.mark.asyncio
async def test_calendar_create_event_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "event": {"event_id": "ev1", "title": "Demo"}})
    handler = make_calendar_create_event_handler(client)
    result = await handler({
        "title": "Demo",
        "start_time": "2026-05-20T14:00:00",
        "duration_minutes": 60,
        "attendees": ["alice@example.com"],
    })
    client.post.assert_called_once_with(
        "/calendar/calendar_create_event",
        json={
            "title": "Demo",
            "start_time": "2026-05-20T14:00:00",
            "duration_minutes": 60,
            "attendees": ["alice@example.com"],
        },
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["event"]["title"] == "Demo"


@pytest.mark.asyncio
async def test_calendar_create_event_minimal(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "event": {"event_id": "ev2"}})
    handler = make_calendar_create_event_handler(client)
    await handler({"title": "Sync", "start_time": "2026-05-20T09:00:00"})
    client.post.assert_called_once_with(
        "/calendar/calendar_create_event",
        json={"title": "Sync", "start_time": "2026-05-20T09:00:00"},
    )


@pytest.mark.asyncio
async def test_calendar_create_event_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_calendar_create_event_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"title": "x", "start_time": "2026-01-01T00:00:00"})
    assert ei.value.kind == "auth"


def test_calendar_create_event_tool_spec_shape():
    t = calendar_create_event_tool_spec()
    assert t.name == "calendar_create_event"
    required = t.inputSchema["required"]
    assert "title" in required
    assert "start_time" in required
    assert "attendees" in t.inputSchema["properties"]
