"""
MCP User Header Injection Filter

This Pipeline filter intercepts tool calls and injects the user email header
before forwarding to the MCP Proxy. This solves the multi-tenant authentication
problem where Open WebUI doesn't forward user headers to tool servers.

Deploy this to your Pipelines server.
"""

from typing import Optional, Dict, Any, List
import aiohttp
import json


class Filter:
    """Injects user headers into MCP tool calls for multi-tenant filtering."""

    class Valves:
        def __init__(self):
            self.MCP_PROXY_URL = "http://mcp-proxy:8000"
            self.enabled = True

    def __init__(self):
        self.valves = self.Valves()
        self.name = "MCP User Header Filter"

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        Pre-process incoming messages.
        Intercepts tool calls and adds user headers.
        """
        if not self.valves.enabled:
            return body

        # Get user email
        user_email = ""
        if __user__:
            user_email = __user__.get("email", "")

        # Store user email in body metadata for outlet processing
        if "metadata" not in body:
            body["metadata"] = {}
        body["metadata"]["user_email"] = user_email

        print(f"[MCP Filter] Inlet - User: {user_email}")

        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        Post-process outgoing messages.
        If tool calls are present, execute them with user headers.
        """
        if not self.valves.enabled:
            return body

        user_email = body.get("metadata", {}).get("user_email", "")
        if __user__:
            user_email = __user__.get("email", user_email)

        print(f"[MCP Filter] Outlet - User: {user_email}")

        # Check for tool calls in the response
        messages = body.get("messages", [])
        for msg in messages:
            if msg.get("role") == "assistant":
                tool_calls = msg.get("tool_calls", [])
                for tool_call in tool_calls:
                    func = tool_call.get("function", {})
                    func_name = func.get("name", "")
                    func_args = func.get("arguments", "{}")

                    if func_name:
                        print(f"[MCP Filter] Tool call detected: {func_name}")
                        # Execute with user headers
                        result = await self._execute_tool_with_user(
                            func_name, func_args, user_email
                        )
                        # Update tool call result
                        tool_call["result"] = result

        return body

    async def _execute_tool_with_user(
        self, tool_name: str, arguments: str, user_email: str
    ) -> str:
        """Execute a tool call with proper user headers."""
        try:
            args_dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args_dict = {}

        # Parse tool name to get server and tool
        # Format: server_tool or server/tool
        if "_" in tool_name:
            parts = tool_name.split("_", 1)
            server = parts[0]
            tool = parts[1] if len(parts) > 1 else ""
        else:
            server = tool_name
            tool = ""

        url = f"{self.valves.MCP_PROXY_URL}/{server}/{tool}" if tool else f"{self.valves.MCP_PROXY_URL}/{tool_name}"

        headers = {
            "X-OpenWebUI-User-Email": user_email,
            "Content-Type": "application/json",
        }

        print(f"[MCP Filter] Executing: {url} as {user_email}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=args_dict, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    elif resp.status == 403:
                        return f"Access Denied: {user_email} cannot access {server}"
                    else:
                        return f"Error {resp.status}: {await resp.text()}"
        except Exception as e:
            return f"Error executing tool: {str(e)}"
