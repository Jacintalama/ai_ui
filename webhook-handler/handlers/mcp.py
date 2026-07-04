"""MCP webhook handler — execute MCP tools via webhook triggers."""
from typing import Any, Optional
import logging

from clients.mcp_proxy import MCPProxyClient

logger = logging.getLogger(__name__)


class MCPWebhookHandler:
    """Handler for MCP tool execution via webhooks."""

    def __init__(self, mcp_client: MCPProxyClient):
        self.mcp = mcp_client

    async def handle_tool_request(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] = None
    ) -> dict[str, Any]:
        """
        Execute an MCP tool and return the result.

        Args:
            server_id: MCP server ID (e.g., 'github', 'jira')
            tool_name: Tool name to execute
            arguments: Tool arguments

        Returns:
            Result dict with success status and tool output
        """
        logger.info(f"Executing MCP tool: {server_id}/{tool_name}")

        result = await self.mcp.execute_tool(
            server_id=server_id,
            tool_name=tool_name,
            arguments=arguments or {}
        )

        if result is None:
            logger.error(f"MCP tool execution failed: {server_id}/{tool_name}")
            return {
                "success": False,
                "error": f"Failed to execute {server_id}/{tool_name}"
            }

        logger.info(f"MCP tool {server_id}/{tool_name} completed successfully")
        return {
            "success": True,
            "message": f"Tool {server_id}/{tool_name} executed",
            "result": result
        }
