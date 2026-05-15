"""Factory for stdio MCP servers. Each wrapper hands `build_server` its
name and a list of (Tool, handler) pairs; the factory returns a configured
mcp.server.Server.

Tool responses use a consistent envelope:
  success:  {"ok": true, "data": <result>}
  failure:  {"error": "<kind>", "detail"?: "...", "retry_after"?: N}

GatewayError is mapped automatically. Any other exception becomes
{"error": "internal"} — the agent never sees the original message,
which protects against unintended leaks per the spec's secret hygiene
section.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from mcp.server import Server
from mcp.types import Tool, TextContent

from .errors import GatewayError


ToolHandler = Callable[[dict], Awaitable[list[TextContent]]]


def ok_response(data) -> list[TextContent]:
    return [TextContent(type="text",
                        text=json.dumps({"ok": True, "data": data}))]


def error_response(err: Exception) -> list[TextContent]:
    if isinstance(err, GatewayError):
        body: dict = {"error": err.kind}
        if err.detail:
            body["detail"] = err.detail
        if err.retry_after is not None:
            body["retry_after"] = err.retry_after
    else:
        body = {"error": "internal"}
    return [TextContent(type="text", text=json.dumps(body))]


def build_server(name: str, tools: list[tuple[Tool, ToolHandler]]) -> Server:
    server: Server = Server(name)
    tool_specs = [t for t, _ in tools]
    handlers = {t.name: h for t, h in tools}

    @server.list_tools()
    async def _list() -> list[Tool]:
        return tool_specs

    @server.call_tool()
    async def _call(tool_name: str, arguments: dict) -> list[TextContent]:
        h = handlers.get(tool_name)
        if h is None:
            return error_response(ValueError(f"unknown tool: {tool_name}"))
        try:
            return await h(arguments)
        except GatewayError as e:
            return error_response(e)
        except Exception as e:  # noqa: BLE001 — paranoia: sanitize all errors
            return error_response(e)

    return server


async def run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())
