"""io-meeting-kb MCP wrapper — exposes meeting knowledge base search, get, and list tools."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def meeting_kb_search_tool_spec() -> Tool:
    return Tool(
        name="meeting_kb_search",
        description=(
            "Semantic search across meeting summaries in the knowledge base. "
            "Find meetings about specific topics, with specific people, or within a date range."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — matched semantically against meeting summaries",
                },
                "title_keyword": {
                    "type": "string",
                    "description": "Optional keyword filter on title",
                },
                "date_from": {
                    "type": "string",
                    "description": "Filter: meetings on or after this date (ISO 8601)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter: meetings on or before this date (ISO 8601)",
                },
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter: meetings that include ALL of these participants",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter: meetings that include ANY of these tags",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Max results",
                },
            },
            "required": ["query"],
        },
    )


def meeting_kb_get_tool_spec() -> Tool:
    return Tool(
        name="meeting_kb_get",
        description=(
            "Get full details of a specific meeting from the knowledge base by its UUID. "
            "Use after meeting_kb_search to retrieve the complete text."
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


def meeting_kb_list_tool_spec() -> Tool:
    return Tool(
        name="meeting_kb_list",
        description=(
            "List recent meeting summaries from the knowledge base, ordered by date (newest first). "
            "Use to see what meetings are available before searching."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                    "description": "Number of meetings to return",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Pagination offset",
                },
            },
            "required": [],
        },
    )


def make_meeting_kb_search_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload: dict = {
            "query": args["query"],
            "limit": args.get("limit", 10),
        }
        for key in ("title_keyword", "date_from", "date_to", "participants", "tags"):
            if key in args and args[key] is not None:
                payload[key] = args[key]
        data = await client.post("/meeting-kb/search_meetings", json=payload)
        return ok_response(data)
    return handler


def make_meeting_kb_get_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        data = await client.post("/meeting-kb/get_meeting", json={"meeting_id": args["meeting_id"]})
        return ok_response(data)
    return handler


def make_meeting_kb_list_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload = {
            "limit": args.get("limit", 20),
            "offset": args.get("offset", 0),
        }
        data = await client.post("/meeting-kb/list_meetings", json=payload)
        return ok_response(data)
    return handler
