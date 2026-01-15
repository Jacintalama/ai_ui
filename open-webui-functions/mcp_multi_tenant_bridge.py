"""
MCP Multi-Tenant Bridge for Open WebUI

This function bridges Open WebUI to the MCP Proxy Gateway with PROPER USER AUTHENTICATION.
It injects the X-OpenWebUI-User-Email header that the external tool server calls DON'T include.

WHY THIS IS NEEDED:
- Open WebUI's tool server integration does NOT forward user headers
- The MCP Proxy needs user email to enforce multi-tenant access control
- This function has access to __user__ context and injects the proper headers

INSTALLATION:
1. Go to Open WebUI Admin Panel -> Workspace -> Functions
2. Click "+" to add new function
3. Paste this ENTIRE code
4. Click "Save"
5. Go to model settings (gpt-5) and enable this function
6. DISABLE the direct "MCP Proxy Gateway" tool server (it doesn't send user headers)

USAGE:
- "What servers do I have access to?"
- "Search GitHub for kubernetes repos"
- "List files in /data directory"
"""

import httpx
import json
from typing import Optional, Callable, Any
from pydantic import BaseModel, Field


class Tools:
    """MCP Multi-Tenant Bridge - Enables multi-tenant MCP tools with proper user authentication."""

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

    def _get_user_headers(self, __user__: dict) -> dict:
        """Build headers with user context for multi-tenant filtering."""
        # Extract groups from __user__ context
        # Open WebUI stores groups when ENABLE_OAUTH_GROUP_MANAGEMENT=true
        groups = __user__.get("groups", [])
        if isinstance(groups, list):
            # Groups might be list of dicts with 'name' key or list of strings
            if groups and isinstance(groups[0], dict):
                groups_str = ",".join([g.get("name", "") for g in groups if g.get("name")])
            else:
                groups_str = ",".join([str(g) for g in groups])
        else:
            groups_str = str(groups) if groups else ""

        return {
            "X-OpenWebUI-User-Email": __user__.get("email", ""),
            "X-OpenWebUI-User-Id": __user__.get("id", ""),
            "X-OpenWebUI-User-Name": __user__.get("name", ""),
            "X-OpenWebUI-User-Role": __user__.get("role", "user"),
            "X-OpenWebUI-User-Groups": groups_str,  # Entra ID groups for multi-tenant
            "X-User-Groups": groups_str,  # Alternative header name
            "Content-Type": "application/json",
        }

    async def list_my_servers(
        self,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List all MCP servers you have access to based on your user permissions.
        Shows which tool servers (GitHub, Filesystem, Linear, etc.) you can use.

        :return: List of available MCP servers with their tools
        """
        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Checking access for {user_email}...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{self.valves.MCP_PROXY_URL}/servers",
                    headers=self._get_user_headers(__user__)
                )

                if response.status_code == 200:
                    data = response.json()
                    servers = data.get("servers", [])

                    if not servers:
                        return f"No servers available for {user_email}. Contact admin for access."

                    result = f"## Available Servers for {user_email}\n\n"
                    result += f"**Total:** {len(servers)} server(s)\n\n"

                    for server in servers:
                        status = "✅ Enabled" if server.get("enabled", True) else "❌ Disabled"
                        result += f"### {server['name']} ({server['id']})\n"
                        result += f"- Status: {status}\n"
                        result += f"- Description: {server.get('description', 'N/A')}\n\n"

                    if __event_emitter__:
                        await __event_emitter__({
                            "type": "status",
                            "data": {"description": f"Found {len(servers)} servers", "done": True}
                        })

                    return result
                else:
                    return f"Error: {response.status_code} - {response.text}"

        except Exception as e:
            return f"Error connecting to MCP Proxy: {str(e)}"

    async def github_search(
        self,
        query: str,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Search GitHub repositories. Requires GitHub server access.

        :param query: Search query (e.g., "kubernetes", "machine learning python")
        :return: List of matching repositories
        """
        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Searching GitHub for '{query}'...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.valves.MCP_PROXY_URL}/github/search_repositories",
                    json={"query": query},
                    headers=self._get_user_headers(__user__)
                )

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "Search complete", "done": True}
                    })

                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and "items" in data:
                        items = data["items"][:10]  # Top 10
                        result = f"## GitHub Search: '{query}'\n\n"
                        result += f"Found {data.get('total_count', len(items))} repositories\n\n"
                        for repo in items:
                            stars = repo.get("stargazers_count", 0)
                            result += f"- **[{repo['full_name']}]({repo['html_url']})** ⭐ {stars}\n"
                            result += f"  {repo.get('description', 'No description')[:100]}\n\n"
                        return result
                    return f"Results:\n```json\n{json.dumps(data, indent=2)[:2000]}\n```"
                elif response.status_code == 403:
                    return f"**Access Denied:** {user_email} does not have access to GitHub server."
                else:
                    return f"Error ({response.status_code}): {response.text}"

        except Exception as e:
            return f"Error: {str(e)}"

    async def list_files(
        self,
        path: str = "/data",
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List files in a directory. Requires Filesystem server access.

        :param path: Directory path to list (default: /data)
        :return: List of files and directories
        """
        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Listing files in {path}...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.valves.MCP_PROXY_URL}/filesystem/list_directory",
                    json={"path": path},
                    headers=self._get_user_headers(__user__)
                )

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "Listing complete", "done": True}
                    })

                if response.status_code == 200:
                    return f"## Files in {path}\n\n```\n{response.text}\n```"
                elif response.status_code == 403:
                    return f"**Access Denied:** {user_email} does not have access to Filesystem server."
                else:
                    return f"Error ({response.status_code}): {response.text}"

        except Exception as e:
            return f"Error: {str(e)}"

    async def read_file(
        self,
        path: str,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Read contents of a file. Requires Filesystem server access.

        :param path: Full path to the file to read
        :return: File contents
        """
        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Reading {path}...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.valves.MCP_PROXY_URL}/filesystem/read_file",
                    json={"path": path},
                    headers=self._get_user_headers(__user__)
                )

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "Read complete", "done": True}
                    })

                if response.status_code == 200:
                    return f"## Contents of {path}\n\n```\n{response.text}\n```"
                elif response.status_code == 403:
                    return f"**Access Denied:** {user_email} does not have access to Filesystem server."
                else:
                    return f"Error ({response.status_code}): {response.text}"

        except Exception as e:
            return f"Error: {str(e)}"

    async def debug_my_context(
        self,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Debug tool to see your user context including groups.
        Use this to verify Entra ID groups are being passed correctly.

        :return: Your user context information
        """
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Reading user context...", "done": True}
            })

        result = "## Your User Context\n\n"
        result += f"**Email:** {__user__.get('email', 'N/A')}\n"
        result += f"**Name:** {__user__.get('name', 'N/A')}\n"
        result += f"**Role:** {__user__.get('role', 'N/A')}\n"
        result += f"**ID:** {__user__.get('id', 'N/A')}\n\n"

        # Show groups
        groups = __user__.get("groups", [])
        result += f"## Groups ({len(groups) if isinstance(groups, list) else 'N/A'})\n\n"
        if groups:
            if isinstance(groups, list):
                for g in groups:
                    if isinstance(g, dict):
                        result += f"- {g.get('name', g)}\n"
                    else:
                        result += f"- {g}\n"
            else:
                result += f"- {groups}\n"
        else:
            result += "_No groups found. Ensure ENABLE_OAUTH_GROUP_MANAGEMENT=true in Open WebUI._\n"

        # Show all keys in __user__
        result += f"\n## All Context Keys\n\n"
        result += f"```json\n{json.dumps(list(__user__.keys()), indent=2)}\n```\n"

        return result

    async def execute_mcp_tool(
        self,
        server: str,
        tool: str,
        arguments: str = "{}",
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Execute any MCP tool on any server you have access to.
        Use list_my_servers first to see available servers.

        :param server: Server ID (e.g., 'github', 'filesystem', 'linear')
        :param tool: Tool name (e.g., 'search_repositories', 'list_directory')
        :param arguments: JSON string of arguments (e.g., '{"query": "mcp"}')
        :return: Tool execution result
        """
        user_email = __user__.get("email", "")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Executing {server}/{tool}...", "done": False}
            })

        try:
            args_dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"Error: Invalid JSON arguments: {arguments}"

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.valves.MCP_PROXY_URL}/{server}/{tool}",
                    json=args_dict,
                    headers=self._get_user_headers(__user__)
                )

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"Completed {server}/{tool}", "done": True}
                    })

                if response.status_code == 200:
                    try:
                        data = response.json()
                        return f"**Result:**\n```json\n{json.dumps(data, indent=2)[:3000]}\n```"
                    except:
                        return f"**Result:**\n```\n{response.text[:3000]}\n```"
                elif response.status_code == 403:
                    return f"**Access Denied:** {user_email} does not have access to '{server}' server."
                elif response.status_code == 404:
                    return f"**Not Found:** Server '{server}' or tool '{tool}' does not exist."
                else:
                    return f"**Error ({response.status_code}):** {response.text}"

        except Exception as e:
            return f"Error: {str(e)}"
