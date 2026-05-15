import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_meetings.tools import (
    meetings_list_tool_spec,
    meetings_get_tool_spec,
    make_meetings_list_handler,
    make_meetings_get_handler,
)


# --- meetings_list ---

@pytest.mark.asyncio
async def test_meetings_list_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.get = AsyncMock(return_value=[{"id": "abc", "title": "Standup"}])
    handler = make_meetings_list_handler(client)
    result = await handler({})
    client.get.assert_called_once_with("/meetings/")
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"][0]["title"] == "Standup"


@pytest.mark.asyncio
async def test_meetings_list_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.get = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_meetings_list_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({})
    assert ei.value.kind == "auth"


def test_meetings_list_tool_spec_shape():
    t = meetings_list_tool_spec()
    assert t.name == "meetings_list"
    # No required fields
    assert t.inputSchema.get("required", []) == []


# --- meetings_get ---

@pytest.mark.asyncio
async def test_meetings_get_calls_gateway(monkeypatch):
    client = AsyncMock()
    meeting_data = {"id": "abc-123", "title": "Q2 Planning", "summary": "discussed goals"}
    client.get = AsyncMock(return_value=meeting_data)
    handler = make_meetings_get_handler(client)
    result = await handler({"meeting_id": "abc-123"})
    client.get.assert_called_once_with("/meetings/abc-123")
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["title"] == "Q2 Planning"


@pytest.mark.asyncio
async def test_meetings_get_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.get = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_meetings_get_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"meeting_id": "x"})
    assert ei.value.kind == "auth"


def test_meetings_get_tool_spec_shape():
    t = meetings_get_tool_spec()
    assert t.name == "meetings_get"
    assert "meeting_id" in t.inputSchema["properties"]
    assert "meeting_id" in t.inputSchema["required"]
