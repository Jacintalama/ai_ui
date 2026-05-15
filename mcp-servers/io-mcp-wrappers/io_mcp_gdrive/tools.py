"""io-gdrive MCP wrapper — exposes Google Drive search, read, and list tools."""
from __future__ import annotations

import json

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response, error_response
from io_mcp_base.errors import GatewayError

_5MB = 5_000_000


def gdrive_search_tool_spec() -> Tool:
    return Tool(
        name="gdrive_search",
        description=(
            "Search for files across your Google Drive by name or content. "
            "Returns file names, types, IDs and links."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'quarterly report', 'budget 2024')"},
                "file_type": {
                    "type": "string",
                    "description": "Filter by type: 'document', 'spreadsheet', 'presentation', 'pdf', 'folder'",
                },
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["query"],
        },
    )


def gdrive_read_file_tool_spec() -> Tool:
    return Tool(
        name="gdrive_read_file",
        description=(
            "Read the content of a Google Drive file by its ID. "
            "Returns text content for documents and spreadsheets. Max 5 MB."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID to read"},
            },
            "required": ["file_id"],
        },
    )


def gdrive_list_files_tool_spec() -> Tool:
    return Tool(
        name="gdrive_list_files",
        description=(
            "List files in a Google Drive folder. "
            "Use folder_id='root' for top-level files, or omit for root."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": ["string", "null"],
                    "description": "Folder ID to list files from. Use 'root' for top-level or omit for root.",
                },
            },
            "required": [],
        },
    )


def make_gdrive_search_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload: dict = {"query": args["query"], "page_size": args.get("page_size", 20)}
        if "file_type" in args and args["file_type"] is not None:
            payload["file_type"] = args["file_type"]
        data = await client.post("/gdrive/gdrive_search_files", json=payload)
        return ok_response(data)
    return handler


def make_gdrive_read_file_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        data = await client.post("/gdrive/gdrive_read_file", json={"file_id": args["file_id"]})
        # 5MB cap: check size_bytes field OR content length
        if isinstance(data, dict):
            size_bytes = data.get("size_bytes")
            if size_bytes is not None and size_bytes > _5MB:
                return error_response(GatewayError(kind="server", detail="too_large"))
            content = data.get("content")
            if content is not None and len(str(content)) > _5MB:
                return error_response(GatewayError(kind="server", detail="too_large"))
        return ok_response(data)
    return handler


def make_gdrive_list_files_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload = {"folder_id": args.get("folder_id", None)}
        data = await client.post("/gdrive/gdrive_list_files", json=payload)
        return ok_response(data)
    return handler
