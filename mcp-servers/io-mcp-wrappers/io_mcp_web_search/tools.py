"""io-web-search MCP wrapper — exposes the platform's web-search service
as a single MCP tool callable by the claude-agent."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def web_search_tool_spec() -> Tool:
    return Tool(
        name="web_search",
        description=(
            "Search the public web via the platform's web-search service. "
            "Returns up to `count` results with title, url, and snippet."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
    )


def make_web_search_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload = {"query": args["query"], "count": args.get("count", 5)}
        data = await client.post("/web-search/web_search", json=payload)
        return ok_response(data)
    return handler
