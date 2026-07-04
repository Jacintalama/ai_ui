"""MCP Proxy client for executing MCP tools directly."""
import httpx
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class MCPProxyClient:
    """Client for calling MCP Proxy tool endpoints directly."""

    def __init__(self, base_url: str, user_email: str, user_groups: str):
        self.base_url = base_url.rstrip("/")
        self.user_email = user_email
        self.user_groups = user_groups
        self.timeout = 30.0

    async def execute_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] = None
    ) -> Optional[dict[str, Any]]:
        """
        Execute an MCP tool via the MCP Proxy.

        Args:
            server_id: MCP server ID (e.g., 'github', 'jira', 'linear')
            tool_name: Tool name (e.g., 'get_me', 'create_issue')
            arguments: Tool arguments dict

        Returns:
            Tool response dict, or None on error
        """
        # Build candidate tool paths. MCP servers vary:
        #   GitHub mcpo:  /get_me  (no prefix in endpoint)
        #   ClickUp mcpo: /clickup_get_workspaces  (prefix in endpoint)
        # Try the name as-given first, then with server prefix stripped.
        candidates = [tool_name]
        prefix = f"{server_id}_"
        if tool_name.startswith(prefix):
            candidates.append(tool_name[len(prefix):])

        headers = {
            "X-User-Email": self.user_email,
            "X-User-Groups": self.user_groups,
            "Content-Type": "application/json"
        }
        body = arguments or {}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for name in candidates:
                    url = f"{self.base_url}/{server_id}/{name}"
                    response = await client.post(url, json=body, headers=headers)
                    if response.status_code == 404 and name != candidates[-1]:
                        logger.debug(f"MCP tool {server_id}/{name} not found, trying next")
                        continue
                    response.raise_for_status()
                    result = response.json()
                    logger.info(f"MCP tool {server_id}/{name} executed successfully")
                    return result

        except httpx.HTTPStatusError as e:
            logger.error(
                f"MCP Proxy error for {server_id}/{tool_name}: "
                f"{e.response.status_code} - {e.response.text}"
            )
            return None
        except httpx.TimeoutException:
            logger.error(f"Timeout calling MCP Proxy for {server_id}/{tool_name}")
            return None
        except Exception as e:
            logger.error(f"Error calling MCP Proxy: {e}")
            return None

    async def list_tools(self, server_id: str) -> Optional[list[dict]]:
        """
        List available tools for an MCP server.

        Args:
            server_id: MCP server ID

        Returns:
            List of tool dicts, or None on error
        """
        url = f"{self.base_url}/tools"
        headers = {
            "X-User-Email": self.user_email,
            "X-User-Groups": self.user_groups
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                all_tools = response.json()
                # Filter to specified server
                server_tools = [
                    t for t in all_tools
                    if t.get("server_id") == server_id
                ]
                return server_tools

        except Exception as e:
            logger.error(f"Error listing MCP tools: {e}")
            return None
