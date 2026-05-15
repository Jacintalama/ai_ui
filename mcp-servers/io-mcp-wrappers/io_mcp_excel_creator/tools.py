"""io-excel-creator MCP wrapper — exposes the Excel workbook creation tool."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response

# Fields that contain binary/HTML blobs that would blow out agent context
_BINARY_FIELDS = frozenset({"download_html", "file_bytes"})


def excel_create_workbook_tool_spec() -> Tool:
    return Tool(
        name="excel_create_workbook",
        description=(
            "Create an Excel (.xlsx) workbook from comma/pipe-separated data. "
            "Returns metadata (filename, row/column counts). Use the returned filename "
            "to describe the result to the user."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Name for the Excel file (without .xlsx extension)",
                },
                "headers": {
                    "type": "string",
                    "description": "Comma-separated column headers (e.g., 'Product,Jan,Feb,Mar')",
                },
                "data": {
                    "type": "string",
                    "description": "Pipe-separated rows with comma-separated values (e.g., 'Widget,100,150,200|Gadget,250,300,350')",
                },
                "include_totals": {
                    "type": "boolean",
                    "default": True,
                    "description": "Add a TOTAL row with SUM formulas",
                },
            },
            "required": ["title", "headers", "data"],
        },
    )


def make_excel_create_workbook_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload: dict = {
            "title": args["title"],
            "headers": args["headers"],
            "data": args["data"],
        }
        if "include_totals" in args:
            payload["include_totals"] = args["include_totals"]
        raw = await client.post("/excel-creator/create_simple_excel", json=payload)
        # Strip binary fields to prevent context blowout
        if isinstance(raw, dict):
            data = {k: v for k, v in raw.items() if k not in _BINARY_FIELDS}
        else:
            data = raw
        return ok_response(data)
    return handler
