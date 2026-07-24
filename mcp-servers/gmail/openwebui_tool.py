"""
title: Gmail
author: AIUI Team
version: 0.1.0
description: Connect your Gmail and draft new emails straight from chat. Drafts are saved to your Gmail Drafts for you to review and send. Nothing is ever sent automatically.
"""

# Native Open WebUI Tool (class Tools) so the model can call these directly,
# without the meta-tools discovery step, and so Open WebUI hands us the real
# signed-in user via __user__ (correct per-user Gmail, no default@local).

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        gmail_url: str = Field(
            default="http://mcp-gmail:8000",
            description="Gmail MCP server URL (internal).",
        )
        public_base_url: str = Field(
            default="https://ai-ui.coolestdomain.win",
            description="Public base URL used to build the Gmail connect link.",
        )
        timeout_seconds: int = Field(default=30, description="HTTP timeout.")

    def __init__(self):
        self.valves = self.Valves()

    def _connect_link(self, user_email: str) -> str:
        return (f"{self.valves.public_base_url}/gmail/auth/google/start"
                f"?user_email={user_email}")

    # connect_gmail was removed: connecting is handled by the inline Connect
    # card injected by the frontend (integrations-ui.js), so the model only
    # drafts. draft_email still surfaces the connect link if not connected yet.

    async def draft_email(
        self, to: str, subject: str, body: str, __user__: dict = {}
    ) -> str:
        """
        Create a brand-new DRAFT email in the user's Gmail Drafts folder. The
        draft is never sent; the user reviews and sends it themselves in Gmail.
        Use this whenever the user wants to draft, compose, or write a new email
        to someone.

        :param to: Recipient email address.
        :param subject: Email subject line.
        :param body: Plain-text body of the email.
        :return: Confirmation that the draft was saved, or a Connect Gmail link if the account is not connected yet.
        """
        user_email = __user__.get("email", "default@local")
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                resp = await client.post(
                    f"{self.valves.gmail_url}/gmail_create_draft",
                    json={"to": to, "subject": subject, "body": body},
                    headers={"X-User-Email": user_email},
                )
            data = resp.json()
        except Exception as e:
            return f"Sorry, I could not reach Gmail to create the draft ({e}). Please try again."

        if isinstance(data, dict) and data.get("error"):
            # Not connected: surface the connect link as a clickable button.
            link = self._connect_link(user_email)
            return (f"{data['error']}\n\n**[Connect Gmail]({link})**")

        return (f"Draft saved to your Gmail Drafts.\n\n"
                f"- To: {to}\n- Subject: {subject}\n\n"
                "Open Gmail to review and send it whenever you're ready.")
