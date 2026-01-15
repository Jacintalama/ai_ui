"""
MCP Proxy Bridge Tool for Open WebUI (Kubernetes Version)

This tool bridges Open WebUI to the MCP Proxy Gateway with proper user authentication.
It injects the X-OpenWebUI-User-Email header that the external tool server calls don't include.

For Kubernetes deployment where Open WebUI and MCP Proxy are in the same cluster.

Installation:
1. Go to Open WebUI Admin Panel -> Workspace -> Tools
2. Click "+" to add new tool
3. Paste this code
4. Set visibility to "Public"
5. Click "Save"

Usage:
- "List my available MCP tools"
- "Use google_read_file to read /data/sample.txt"
- "Execute github_list_repos for user Jacintalama"
"""

import httpx
from typing import Optional, Callable, Any
from pydantic import BaseModel, Field


class Tools:
    """MCP Proxy Bridge - Enables multi-tenant MCP tools with proper user authentication."""

    class Valves(BaseModel):
        """Configuration for the MCP Proxy Bridge."""
        MCP_PROXY_URL: str = Field(
            default="http://mcp-proxy:8000",
            description="URL of the MCP Proxy Gateway (Kubernetes internal service)"
        )
        TIMEOUT_SECONDS: int = Field(
            default=30,
            description="Request timeout in seconds"
        )

    def __init__(self):
        self.valves = self.Valves()

    async def mcp_list_tools(
        self,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List all MCP tools available to the current user based on their tenant access.
        Returns a formatted list of tools the user can execute.

        :return: List of available MCP tools with descriptions
        """
        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Fetching tools for {user_email}...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{self.valves.MCP_PROXY_URL}/tools",
                    headers={
                        "X-OpenWebUI-User-Email": user_email,
                        "X-OpenWebUI-User-Id": __user__.get("id", ""),
                        "X-OpenWebUI-User-Name": __user__.get("name", ""),
                        "X-OpenWebUI-User-Role": __user__.get("role", "user"),
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    tools = data.get("tools", [])

                    if not tools:
                        return f"No tools available for user {user_email}. You may not have access to any tenants."

                    # Format tools list
                    result = f"## Available MCP Tools for {user_email}\n\n"
                    result += f"**Tenant Access:** {data.get('tenant_count', 0)} tenant(s)\n"
                    result += f"**Total Tools:** {data.get('tool_count', 0)}\n\n"

                    # Group by tenant
                    by_tenant = {}
                    for tool in tools:
                        tenant = tool.get("tenant_name", "Unknown")
                        if tenant not in by_tenant:
                            by_tenant[tenant] = []
                        by_tenant[tenant].append(tool)

                    for tenant, tenant_tools in by_tenant.items():
                        result += f"### {tenant}\n"
                        for tool in tenant_tools:
                            result += f"- **{tool['name']}**: {tool.get('description', 'No description')}\n"
                        result += "\n"

                    if __event_emitter__:
                        await __event_emitter__({
                            "type": "status",
                            "data": {"description": f"Found {len(tools)} tools", "done": True}
                        })

                    return result
                else:
                    return f"Error fetching tools: {response.status_code} - {response.text}"

        except Exception as e:
            return f"Error connecting to MCP Proxy: {str(e)}"

    async def mcp_execute(
        self,
        tool_name: str,
        arguments: str = "{}",
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Execute an MCP tool with the given arguments.
        User's tenant access is automatically enforced by the MCP Proxy.

        :param tool_name: The name of the MCP tool to execute (e.g., 'google_read_file', 'github_search_repositories')
        :param arguments: JSON string of arguments to pass to the tool (e.g., '{"path": "/data"}')
        :return: The result of the tool execution
        """
        import json

        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Executing {tool_name}...", "done": False}
            })

        # Parse arguments
        try:
            args_dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"Error: Invalid JSON arguments: {arguments}"

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.valves.MCP_PROXY_URL}/{tool_name}",
                    json=args_dict,
                    headers={
                        "X-OpenWebUI-User-Email": user_email,
                        "X-OpenWebUI-User-Id": __user__.get("id", ""),
                        "X-OpenWebUI-User-Name": __user__.get("name", ""),
                        "X-OpenWebUI-User-Role": __user__.get("role", "user"),
                        "Content-Type": "application/json",
                    }
                )

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"Completed {tool_name}", "done": True}
                    })

                if response.status_code == 200:
                    return f"**Tool Result:**\n```\n{response.text}\n```"
                elif response.status_code == 403:
                    return f"**Access Denied:** You ({user_email}) do not have permission to use tool '{tool_name}'. This tool belongs to a tenant you don't have access to."
                elif response.status_code == 404:
                    return f"**Tool Not Found:** The tool '{tool_name}' does not exist. Use mcp_list_tools to see available tools."
                else:
                    return f"**Error ({response.status_code}):** {response.text}"

        except Exception as e:
            return f"Error executing tool: {str(e)}"

    async def mcp_tenants(
        self,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List the tenants the current user has access to.

        :return: List of tenants with their details
        """
        user_email = __user__.get("email", "")

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{self.valves.MCP_PROXY_URL}/tenants",
                    headers={
                        "X-OpenWebUI-User-Email": user_email,
                        "X-OpenWebUI-User-Id": __user__.get("id", ""),
                        "X-OpenWebUI-User-Name": __user__.get("name", ""),
                        "X-OpenWebUI-User-Role": __user__.get("role", "user"),
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    tenants = data.get("tenants", [])

                    if not tenants:
                        return f"User {user_email} does not have access to any tenants."

                    result = f"## Tenant Access for {user_email}\n\n"
                    for tenant in tenants:
                        status = "Enabled" if tenant.get("enabled", True) else "Disabled"
                        result += f"- **{tenant['display_name']}** ({tenant['tenant_id']}): {status}\n"

                    return result
                else:
                    return f"Error: {response.status_code} - {response.text}"

        except Exception as e:
            return f"Error fetching tenants: {str(e)}"
