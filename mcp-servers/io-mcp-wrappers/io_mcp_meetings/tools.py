"""io-meetings MCP wrapper — exposes meetings list and get tools."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def meetings_list_tool_spec() -> Tool:
    return Tool(
        name="meetings_list",
        description=(
            "List all stored meetings from the meetings service. "
            "Returns meeting IDs, titles, dates, and attendees."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )


def meetings_get_tool_spec() -> Tool:
    return Tool(
        name="meetings_get",
        description=(
            "Get full details of a specific meeting by its ID. "
            "Returns title, date, attendees, summary, transcript, and links."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "meeting_id": {
                    "type": "string",
                    "description": "UUID of the meeting to retrieve",
                },
            },
            "required": ["meeting_id"],
        },
    )


def make_meetings_list_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        data = await client.get("/meetings/")
        return ok_response(data)
    return handler


def make_meetings_get_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        meeting_id = args["meeting_id"]
        data = await client.get(f"/meetings/{meeting_id}")
        return ok_response(data)
    return handler
