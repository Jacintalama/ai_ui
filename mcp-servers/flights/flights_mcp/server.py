"""MCP stdio server exposing the search_flights tool.

The tool body is split into `call_search_flights` (testable, takes api_key
as a parameter) and the MCP-registered wrapper (reads api_key from env).
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .duffel import DuffelClient, DuffelError


server: Server = Server("flights")


async def call_search_flights(
    *,
    api_key: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None = None,
    passengers: int = 1,
    cabin: str = "economy",
) -> list[dict[str, Any]] | dict[str, Any]:
    """Pure-Python entrypoint - used by tests AND the MCP wrapper.

    Returns a list of offer dicts on success, or a structured error dict
    matching the spec's error mapping.
    """
    if not api_key:
        return {"error": "auth", "detail": "DUFFEL_API_KEY not set"}
    client = DuffelClient(api_key=api_key)
    try:
        offers = await client.search_flights(
            origin=origin, destination=destination,
            depart_date=depart_date, return_date=return_date,
            passengers=passengers, cabin=cabin,
        )
    except DuffelError as e:
        out: dict[str, Any] = {"error": e.kind}
        if e.kind == "auth":
            out["detail"] = "DUFFEL_API_KEY invalid"
        elif e.kind == "rate_limit":
            out["retry_after"] = e.retry_after or 60
        elif e.detail:
            out["detail"] = e.detail
        return out
    return [o.model_dump() for o in offers]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_flights",
            description=(
                "Search real flight offers from the Duffel sandbox. "
                "Returns up to 6 offers sorted by price ascending."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "IATA code, e.g. LAX"},
                    "destination": {"type": "string", "description": "IATA code, e.g. NRT"},
                    "depart_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
                    "return_date": {"type": "string"},
                    "passengers": {"type": "integer", "minimum": 1, "default": 1},
                    "cabin": {"type": "string",
                              "enum": ["economy", "premium_economy", "business", "first"],
                              "default": "economy"},
                },
                "required": ["origin", "destination", "depart_date"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "search_flights":
        raise ValueError(f"unknown tool: {name}")
    result = await call_search_flights(
        api_key=os.environ.get("DUFFEL_API_KEY", ""),
        **arguments,
    )
    import json
    return [TextContent(type="text", text=json.dumps(result))]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
