"""Automation webhook handler — delegates to the Webhook Automation pipe function."""
from typing import Any
import json
import logging

from clients.openwebui import OpenWebUIClient

logger = logging.getLogger(__name__)


class AutomationWebhookHandler:
    """Handler that wraps payloads and sends them to the Webhook Automation pipe."""

    def __init__(self, openwebui_client: OpenWebUIClient, pipe_model: str):
        self.openwebui = openwebui_client
        self.pipe_model = pipe_model

    async def handle_request(
        self,
        payload: dict[str, Any],
        source: str = "webhook",
        instructions: str = "",
    ) -> dict[str, Any]:
        """
        Wrap the payload in a structured message and call the pipe function.

        The pipe function (running inside Open WebUI) will:
        1. Fetch available MCP tools
        2. Ask the real LLM which tools to call
        3. Execute the selected tools
        4. Summarize the results

        Args:
            payload: Raw webhook payload (any JSON)
            source: Origin of the request (e.g. "github", "slack", "manual")
            instructions: Optional natural-language instructions for the AI

        Returns:
            Result dict with success status and pipe response
        """
        # Build the structured message the pipe function expects
        structured = {
            "source": source,
            "instructions": instructions,
            "payload": payload,
        }

        messages = [
            {"role": "user", "content": json.dumps(structured, default=str)}
        ]

        logger.info(
            f"Automation request: source={source}, model={self.pipe_model}, "
            f"instructions={instructions[:80]!r}"
        )

        response = await self.openwebui.chat_completion(
            messages=messages,
            model=self.pipe_model,
        )

        if not response:
            logger.error("Automation pipe returned no response")
            return {
                "success": False,
                "error": "Automation pipe returned no response. "
                         "Check that the pipe function is installed and enabled in Open WebUI.",
            }

        logger.info("Automation request completed successfully")
        return {
            "success": True,
            "message": "Automation completed",
            "source": source,
            "response": response,
        }
