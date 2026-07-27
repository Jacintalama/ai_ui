"""
title: Gmail
author: AIUI Team
version: 0.2.0
description: Your Gmail assistant in chat. Read unread and important emails, search, summarize, draft, reply, and send (with confirmation). Connecting is a one-click inline button. Per-user: each person uses their own Gmail.
"""

# Native Open WebUI tool (class Tools). The model calls these directly and OWUI
# injects the signed-in user via __user__, so every action is per-user. When a
# call comes back "not connected", we return the server's connect message which
# contains the /auth/google/start URL; the frontend turns that into an inline
# Connect button (see integrations-ui.js linkifyConnectButtons).

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        gmail_url: str = Field(default="http://mcp-gmail:8000")
        public_base_url: str = Field(default="https://ai-ui.coolestdomain.win")
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    # --- internals -------------------------------------------------------
    async def _post(self, path: str, payload: dict, user_email: str) -> dict:
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
            r = await client.post(
                f"{self.valves.gmail_url}/{path}",
                json=payload,
                headers={"X-User-Email": user_email},
            )
            try:
                return r.json()
            except Exception:
                return {"error": f"Gmail returned an unexpected response ({r.status_code})."}

    def _email(self, __user__: dict) -> str:
        return (__user__ or {}).get("email", "default@local")

    def _fmt_list(self, data: dict, empty_msg: str) -> str:
        if isinstance(data, dict) and data.get("error"):
            return data["error"]  # not connected -> connect URL (frontend buttons it)
        emails = data.get("emails", []) if isinstance(data, dict) else []
        if not emails:
            return empty_msg
        lines = []
        for e in emails:
            flag = "  **unread**" if e.get("unread") else ""
            lines.append(
                f"- **{e.get('subject', '(no subject)')}** from {e.get('from', '?')}"
                f" ({e.get('date', '')}){flag}\n  {e.get('snippet', '')}\n  `id: {e.get('id')}`"
            )
        return "\n".join(lines)

    # --- reading / triage ------------------------------------------------
    async def list_unread_emails(self, max_results: int = 15, __user__: dict = {}) -> str:
        """
        List the user's UNREAD emails (sender, subject, snippet, id). Use when
        the user asks what's unread, new, or needs attention.

        :param max_results: How many to return (max 50).
        :return: A formatted list of unread emails, or a connect prompt if Gmail isn't linked.
        """
        data = await self._post("gmail_list_emails",
                                {"label": "INBOX", "unread_only": True, "max_results": max_results},
                                self._email(__user__))
        return self._fmt_list(data, "You have no unread emails.")

    async def list_important_emails(self, max_results: int = 15, __user__: dict = {}) -> str:
        """
        List emails Gmail has flagged IMPORTANT. Use when the user asks what's
        important or what matters most.

        :param max_results: How many to return (max 50).
        :return: A formatted list of important emails, or a connect prompt if Gmail isn't linked.
        """
        data = await self._post("gmail_list_emails",
                                {"label": "IMPORTANT", "max_results": max_results},
                                self._email(__user__))
        return self._fmt_list(data, "No important emails found.")

    async def list_recent_emails(self, max_results: int = 15, __user__: dict = {}) -> str:
        """
        List the most recent emails in the inbox. Use when the user asks to see
        their latest emails or inbox.

        :param max_results: How many to return (max 50).
        :return: A formatted list of recent emails, or a connect prompt if Gmail isn't linked.
        """
        data = await self._post("gmail_list_emails",
                                {"label": "INBOX", "max_results": max_results},
                                self._email(__user__))
        return self._fmt_list(data, "Your inbox looks empty.")

    async def search_emails(self, query: str, max_results: int = 15, __user__: dict = {}) -> str:
        """
        Search Gmail with a query. Supports Gmail operators like from:, to:,
        subject:, after:, before:, has:attachment. Use to find specific emails.

        :param query: Gmail search query, e.g. "from:alice subject:invoice after:2026/01/01".
        :param max_results: How many results (max 50).
        :return: A formatted list of matching emails, or a connect prompt if Gmail isn't linked.
        """
        data = await self._post("gmail_search_emails",
                                {"query": query, "max_results": max_results},
                                self._email(__user__))
        return self._fmt_list(data, f"No emails matched: {query}")

    async def read_email(self, message_id: str, __user__: dict = {}) -> str:
        """
        Read the full content of one email by its id (from a list/search result).
        Use to read or summarize a specific message.

        :param message_id: The Gmail message id (shown as `id:` in list results).
        :return: The email's sender, subject, date, and full body, or a connect prompt if not linked.
        """
        data = await self._post("gmail_read_email", {"message_id": message_id},
                                self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        subject = data.get("subject", "(no subject)")
        frm = data.get("from", "?")
        date = data.get("date", "")
        body = data.get("body") or data.get("content") or data.get("snippet") or ""
        return f"**From:** {frm}\n**Subject:** {subject}\n**Date:** {date}\n\n{body}"

    # --- writing ---------------------------------------------------------
    async def draft_email(self, to: str, subject: str, body: str, __user__: dict = {}) -> str:
        """
        Create a brand-new DRAFT email in the user's Gmail Drafts (never sent).
        Use when the user wants to draft, compose, or prepare a new email.

        :param to: Recipient email address.
        :param subject: Email subject line.
        :param body: Plain-text body.
        :return: Confirmation the draft was saved, or a connect prompt if Gmail isn't linked.
        """
        data = await self._post("gmail_create_draft",
                                {"to": to, "subject": subject, "body": body},
                                self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        return (f"Draft saved to your Gmail Drafts.\n\n- To: {to}\n- Subject: {subject}\n\n"
                "Open Gmail to review and send it, or tell me what to change.")

    async def reply_to_email(self, message_id: str, body: str, __user__: dict = {}) -> str:
        """
        Create a DRAFT reply to an existing email (recipient and subject are
        filled in automatically from the original). Use when the user wants to
        reply to a message they were shown.

        :param message_id: The Gmail message id of the email being replied to.
        :param body: The reply text.
        :return: Confirmation the draft reply was saved, or a connect prompt if not linked.
        """
        data = await self._post("gmail_create_draft_reply",
                                {"message_id": message_id, "body": body},
                                self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        return ("Draft reply saved to your Gmail Drafts. Open Gmail to review and send it, "
                "or tell me to send it and I'll confirm first.")

    async def send_email(self, to: str, subject: str, body: str,
                         cc: str = None, bcc: str = None, __user__: dict = {}) -> str:
        """
        SEND a new email immediately from the user's Gmail. IMPORTANT: only call
        this AFTER you have shown the user the full email (to, subject, body) and
        they have explicitly said to send it. If they have not confirmed, do NOT
        call this; draft it or ask them to confirm first.

        :param to: Recipient email address.
        :param subject: Email subject line.
        :param body: Plain-text body.
        :param cc: Optional CC recipients (comma-separated).
        :param bcc: Optional BCC recipients (comma-separated).
        :return: Confirmation the email was sent, or a connect prompt if Gmail isn't linked.
        """
        payload = {"to": to, "subject": subject, "body": body}
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        data = await self._post("gmail_send_email", payload, self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        if isinstance(data, dict) and data.get("success"):
            return f" Email sent to {to} (subject: {subject})."
        return "I couldn't confirm the send. Please check your Gmail Sent folder."
