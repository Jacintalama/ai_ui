import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_gmail.tools import (
    gmail_search_tool_spec,
    gmail_read_tool_spec,
    gmail_send_tool_spec,
    make_gmail_search_handler,
    make_gmail_read_handler,
    make_gmail_send_handler,
)


# --- gmail_search ---

@pytest.mark.asyncio
async def test_gmail_search_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"emails": [{"id": "abc", "subject": "Hi"}]})
    handler = make_gmail_search_handler(client)
    result = await handler({"query": "from:alice", "max_results": 10})
    client.post.assert_called_once_with(
        "/gmail/gmail_search_emails",
        json={"query": "from:alice", "max_results": 10},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["emails"][0]["subject"] == "Hi"


@pytest.mark.asyncio
async def test_gmail_search_default_max_results(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"emails": []})
    handler = make_gmail_search_handler(client)
    await handler({"query": "test"})
    client.post.assert_called_once_with(
        "/gmail/gmail_search_emails",
        json={"query": "test", "max_results": 20},
    )


@pytest.mark.asyncio
async def test_gmail_search_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_gmail_search_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"query": "x"})
    assert ei.value.kind == "auth"


def test_gmail_search_tool_spec_shape():
    t = gmail_search_tool_spec()
    assert t.name == "gmail_search"
    assert "query" in t.inputSchema["properties"]
    assert "query" in t.inputSchema["required"]


# --- gmail_read ---

@pytest.mark.asyncio
async def test_gmail_read_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"id": "abc", "subject": "Hello", "body": "World"})
    handler = make_gmail_read_handler(client)
    result = await handler({"message_id": "abc"})
    client.post.assert_called_once_with(
        "/gmail/gmail_read_email",
        json={"message_id": "abc"},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["subject"] == "Hello"


@pytest.mark.asyncio
async def test_gmail_read_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_gmail_read_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"message_id": "x"})
    assert ei.value.kind == "auth"


def test_gmail_read_tool_spec_shape():
    t = gmail_read_tool_spec()
    assert t.name == "gmail_read"
    assert "message_id" in t.inputSchema["properties"]
    assert "message_id" in t.inputSchema["required"]


# --- gmail_send ---

@pytest.mark.asyncio
async def test_gmail_send_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "message_id": "sent123"})
    handler = make_gmail_send_handler(client)
    result = await handler({"to": "bob@example.com", "subject": "Hey", "body": "Hello there"})
    client.post.assert_called_once_with(
        "/gmail/gmail_send_email",
        json={"to": "bob@example.com", "subject": "Hey", "body": "Hello there"},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["success"] is True


@pytest.mark.asyncio
async def test_gmail_send_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_gmail_send_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"to": "x@x.com", "subject": "s", "body": "b"})
    assert ei.value.kind == "auth"


def test_gmail_send_tool_spec_shape():
    t = gmail_send_tool_spec()
    assert t.name == "gmail_send"
    assert "to" in t.inputSchema["properties"]
    assert "subject" in t.inputSchema["properties"]
    assert "body" in t.inputSchema["properties"]
    required = t.inputSchema["required"]
    assert "to" in required
    assert "subject" in required
    assert "body" in required
