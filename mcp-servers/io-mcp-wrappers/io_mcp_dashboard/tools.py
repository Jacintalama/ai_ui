"""io-dashboard MCP wrapper — exposes the dashboard creation tool."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def dashboard_create_tool_spec() -> Tool:
    return Tool(
        name="dashboard_create",
        description=(
            "Create a professional HTML executive dashboard with KPI cards and charts. "
            "Returns metadata and an HTML download link."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Dashboard title"},
                "kpis": {
                    "type": "string",
                    "description": "KPIs in format 'Label:Value:Change:trend|...' (e.g., 'Revenue:$1.2M:+15%:up|Users:45K:+8%:up')",
                },
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie"],
                    "description": "Chart type: bar, line, or pie",
                },
                "chart_title": {"type": "string", "description": "Title for the chart"},
                "chart_labels": {
                    "type": "string",
                    "description": "Comma-separated labels (e.g., 'Jan,Feb,Mar,Apr')",
                },
                "chart_data": {
                    "type": "string",
                    "description": "Comma-separated data values (e.g., '100,120,140,160')",
                },
                "theme": {
                    "type": "string",
                    "enum": ["light", "dark"],
                    "description": "Theme: light or dark",
                },
            },
            "required": ["title"],
        },
    )


def make_dashboard_create_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload: dict = {"title": args["title"]}
        for key in ("kpis", "chart_type", "chart_title", "chart_labels", "chart_data", "theme"):
            if key in args and args[key] is not None:
                payload[key] = args[key]
        data = await client.post("/dashboard/create_simple_dashboard", json=payload)
        return ok_response(data)
    return handler
