"""io-gmail MCP wrapper — exposes Gmail search, read, and send tools."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def gmail_search_tool_spec() -> Tool:
    return Tool(
        name="gmail_search",
        description=(
            "Search emails across your Gmail. "
            "Returns subjects, senders, dates, and snippets."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'from:alice subject:invoice after:2026/01/01')",
                },
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "required": ["query"],
        },
    )


def gmail_read_tool_spec() -> Tool:
    return Tool(
        name="gmail_read",
        description="Read the full content of a Gmail email by its message ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID"},
            },
            "required": ["message_id"],
        },
    )


def gmail_send_tool_spec() -> Tool:
    return Tool(
        name="gmail_send",
        description="Send an email from your Gmail account.",
        inputSchema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
                "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
                "bcc": {"type": "string", "description": "BCC recipients (comma-separated)"},
                "reply_to_message_id": {
                    "type": "string",
                    "description": "Message ID to reply to (for threading)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    )


def make_gmail_search_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload = {"query": args["query"], "max_results": args.get("max_results", 20)}
        data = await client.post("/gmail/gmail_search_emails", json=payload)
        return ok_response(data)
    return handler


def make_gmail_read_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        data = await client.post("/gmail/gmail_read_email", json={"message_id": args["message_id"]})
        return ok_response(data)
    return handler


def make_gmail_send_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        # Build payload — never log the body per spec
        payload: dict = {
            "to": args["to"],
            "subject": args["subject"],
            "body": args["body"],
        }
        if args.get("cc"):
            payload["cc"] = args["cc"]
        if args.get("bcc"):
            payload["bcc"] = args["bcc"]
        if args.get("reply_to_message_id"):
            payload["reply_to_message_id"] = args["reply_to_message_id"]
        data = await client.post("/gmail/gmail_send_email", json=payload)
        return ok_response(data)
    return handler
