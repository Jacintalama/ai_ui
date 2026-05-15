import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_meeting_kb.tools import (
    meeting_kb_search_tool_spec,
    meeting_kb_get_tool_spec,
    meeting_kb_list_tool_spec,
    make_meeting_kb_search_handler,
    make_meeting_kb_get_handler,
    make_meeting_kb_list_handler,
)


# --- meeting_kb_search ---

@pytest.mark.asyncio
async def test_meeting_kb_search_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value=[{"id": "m1", "title": "Q2 Planning", "similarity": 0.95}])
    handler = make_meeting_kb_search_handler(client)
    result = await handler({"query": "Q2 goals", "limit": 5})
    client.post.assert_called_once_with(
        "/meeting-kb/search_meetings",
        json={"query": "Q2 goals", "limit": 5},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"][0]["title"] == "Q2 Planning"


@pytest.mark.asyncio
async def test_meeting_kb_search_default_limit(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value=[])
    handler = make_meeting_kb_search_handler(client)
    await handler({"query": "budget"})
    client.post.assert_called_once_with(
        "/meeting-kb/search_meetings",
        json={"query": "budget", "limit": 10},
    )


@pytest.mark.asyncio
async def test_meeting_kb_search_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_meeting_kb_search_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"query": "x"})
    assert ei.value.kind == "auth"


def test_meeting_kb_search_tool_spec_shape():
    t = meeting_kb_search_tool_spec()
    assert t.name == "meeting_kb_search"
    assert "query" in t.inputSchema["properties"]
    assert "query" in t.inputSchema["required"]


# --- meeting_kb_get ---

@pytest.mark.asyncio
async def test_meeting_kb_get_calls_gateway(monkeypatch):
    client = AsyncMock()
    meeting = {"id": "uuid-1", "title": "Sprint Review", "summary": "all done"}
    client.post = AsyncMock(return_value=meeting)
    handler = make_meeting_kb_get_handler(client)
    result = await handler({"meeting_id": "uuid-1"})
    client.post.assert_called_once_with(
        "/meeting-kb/get_meeting",
        json={"meeting_id": "uuid-1"},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["title"] == "Sprint Review"


@pytest.mark.asyncio
async def test_meeting_kb_get_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_meeting_kb_get_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"meeting_id": "x"})
    assert ei.value.kind == "auth"


def test_meeting_kb_get_tool_spec_shape():
    t = meeting_kb_get_tool_spec()
    assert t.name == "meeting_kb_get"
    assert "meeting_id" in t.inputSchema["properties"]
    assert "meeting_id" in t.inputSchema["required"]


# --- meeting_kb_list ---

@pytest.mark.asyncio
async def test_meeting_kb_list_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"total": 2, "meetings": [{"id": "m1"}, {"id": "m2"}]})
    handler = make_meeting_kb_list_handler(client)
    result = await handler({"limit": 5, "offset": 0})
    client.post.assert_called_once_with(
        "/meeting-kb/list_meetings",
        json={"limit": 5, "offset": 0},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["total"] == 2


@pytest.mark.asyncio
async def test_meeting_kb_list_defaults(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"total": 0, "meetings": []})
    handler = make_meeting_kb_list_handler(client)
    await handler({})
    client.post.assert_called_once_with(
        "/meeting-kb/list_meetings",
        json={"limit": 20, "offset": 0},
    )


@pytest.mark.asyncio
async def test_meeting_kb_list_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_meeting_kb_list_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({})
    assert ei.value.kind == "auth"


def test_meeting_kb_list_tool_spec_shape():
    t = meeting_kb_list_tool_spec()
    assert t.name == "meeting_kb_list"
    assert "limit" in t.inputSchema["properties"]
