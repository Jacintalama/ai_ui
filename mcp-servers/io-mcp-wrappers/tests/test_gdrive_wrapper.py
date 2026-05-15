import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_gdrive.tools import (
    gdrive_search_tool_spec,
    gdrive_read_file_tool_spec,
    gdrive_list_files_tool_spec,
    make_gdrive_search_handler,
    make_gdrive_read_file_handler,
    make_gdrive_list_files_handler,
)


# --- gdrive_search ---

@pytest.mark.asyncio
async def test_gdrive_search_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"files": [{"id": "abc", "name": "report.pdf"}]})
    handler = make_gdrive_search_handler(client)
    result = await handler({"query": "quarterly report", "page_size": 5})
    client.post.assert_called_once_with(
        "/gdrive/gdrive_search_files",
        json={"query": "quarterly report", "page_size": 5},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["files"][0]["name"] == "report.pdf"


@pytest.mark.asyncio
async def test_gdrive_search_default_page_size(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"files": []})
    handler = make_gdrive_search_handler(client)
    await handler({"query": "test"})
    client.post.assert_called_once_with(
        "/gdrive/gdrive_search_files",
        json={"query": "test", "page_size": 20},
    )


@pytest.mark.asyncio
async def test_gdrive_search_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_gdrive_search_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"query": "x"})
    assert ei.value.kind == "auth"


def test_gdrive_search_tool_spec_shape():
    t = gdrive_search_tool_spec()
    assert t.name == "gdrive_search"
    assert "query" in t.inputSchema["properties"]
    assert "query" in t.inputSchema["required"]


# --- gdrive_read_file ---

@pytest.mark.asyncio
async def test_gdrive_read_file_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"file_name": "doc.txt", "content": "hello"})
    handler = make_gdrive_read_file_handler(client)
    result = await handler({"file_id": "xyz123"})
    client.post.assert_called_once_with(
        "/gdrive/gdrive_read_file",
        json={"file_id": "xyz123"},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["file_name"] == "doc.txt"


@pytest.mark.asyncio
async def test_gdrive_read_file_too_large_by_content_length(monkeypatch):
    client = AsyncMock()
    big_content = "x" * 5_000_001
    client.post = AsyncMock(return_value={"file_name": "big.txt", "content": big_content})
    handler = make_gdrive_read_file_handler(client)
    result = await handler({"file_id": "big"})
    body = json.loads(result[0].text)
    assert body.get("error") == "server"
    assert body.get("detail") == "too_large"


@pytest.mark.asyncio
async def test_gdrive_read_file_too_large_by_size_bytes(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"file_name": "big.bin", "size_bytes": 5_000_001})
    handler = make_gdrive_read_file_handler(client)
    result = await handler({"file_id": "bigbin"})
    body = json.loads(result[0].text)
    assert body.get("error") == "server"
    assert body.get("detail") == "too_large"


@pytest.mark.asyncio
async def test_gdrive_read_file_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_gdrive_read_file_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({"file_id": "x"})
    assert ei.value.kind == "auth"


def test_gdrive_read_file_tool_spec_shape():
    t = gdrive_read_file_tool_spec()
    assert t.name == "gdrive_read_file"
    assert "file_id" in t.inputSchema["properties"]
    assert "file_id" in t.inputSchema["required"]


# --- gdrive_list_files ---

@pytest.mark.asyncio
async def test_gdrive_list_files_calls_gateway(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"files": [{"id": "f1", "name": "folder"}]})
    handler = make_gdrive_list_files_handler(client)
    result = await handler({"folder_id": "root"})
    client.post.assert_called_once_with(
        "/gdrive/gdrive_list_files",
        json={"folder_id": "root"},
    )
    body = json.loads(result[0].text)
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_gdrive_list_files_null_folder(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"files": []})
    handler = make_gdrive_list_files_handler(client)
    await handler({})
    client.post.assert_called_once_with(
        "/gdrive/gdrive_list_files",
        json={"folder_id": None},
    )


@pytest.mark.asyncio
async def test_gdrive_list_files_auth_error(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth", detail="rejected"))
    handler = make_gdrive_list_files_handler(client)
    with pytest.raises(GatewayError) as ei:
        await handler({})
    assert ei.value.kind == "auth"


def test_gdrive_list_files_tool_spec_shape():
    t = gdrive_list_files_tool_spec()
    assert t.name == "gdrive_list_files"
    assert "folder_id" in t.inputSchema["properties"]
