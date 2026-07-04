"""Generic webhook handler — accepts any JSON and runs AI analysis."""
from typing import Any, Optional
import json
import logging

from clients.openwebui import OpenWebUIClient

logger = logging.getLogger(__name__)


class GenericWebhookHandler:
    """Handler for generic webhook payloads."""

    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        ai_model: str = "gpt-4-turbo"
    ):
        self.openwebui = openwebui_client
        self.ai_model = ai_model

    async def handle_request(
        self,
        payload: dict[str, Any],
        prompt_template: str = "",
        model: str = ""
    ) -> dict[str, Any]:
        """
        Analyze a generic webhook payload with AI.

        Args:
            payload: Any JSON payload
            prompt_template: Optional custom prompt template.
                             Use {payload} as placeholder for the JSON data.
            model: Optional model override

        Returns:
            Result dict with AI analysis
        """
        model = model or self.ai_model

        payload_str = json.dumps(payload, indent=2, default=str)

        if prompt_template:
            user_prompt = prompt_template.replace("{payload}", payload_str)
        else:
            user_prompt = f"""Analyze this webhook payload and provide insights:

```json
{payload_str}
```

Please provide:
1. What this payload represents
2. Key data points
3. Any suggested actions"""

        messages = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant that analyzes webhook payloads. Be concise."
            },
            {"role": "user", "content": user_prompt}
        ]

        analysis = await self.openwebui.chat_completion(
            messages=messages,
            model=model
        )

        if not analysis:
            return {"success": False, "error": "Failed to get AI analysis"}

        return {
            "success": True,
            "message": "Payload analyzed",
            "analysis": analysis
        }
