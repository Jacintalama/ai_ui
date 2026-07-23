"""
title: Email
author: AIUI Team
version: 0.1.0
description: Draft emails from chat. Pick "Email" as your model, then say who to email and what to say. If your Gmail isn't connected you get a one-click Connect button. Drafts are saved to your Gmail Drafts and never sent automatically.
"""

# A selectable pipe (like Fusion) so the reply is fully ours and renders live -
# unlike an outlet filter, whose injected content OWUI does not re-render live.
# Not connected -> return a styled Connect card. Connected -> extract the
# recipient/subject/body (via the OpenAI key already in this container) and
# create a draft in the user's own Gmail. Identity comes from __user__ natively.

import json
import os
import re
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, Field

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _first_sk(value: str) -> str:
    """OWUI may store several keys joined by ';'. Pick the first real sk- key."""
    for part in (value or "").split(";"):
        part = part.strip()
        if part.startswith("sk-"):
            return part
    return (value or "").strip()


class Pipe:
    class Valves(BaseModel):
        gmail_url: str = Field(default="http://mcp-gmail:8000")
        public_base_url: str = Field(default="https://ai-ui.coolestdomain.win")
        openai_api_key: str = Field(
            default_factory=lambda: _first_sk(os.environ.get("OPENAI_API_KEY", "")))
        extract_model: str = Field(default="gpt-4o")
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "email", "name": "Email"}]

    # --- helpers ---------------------------------------------------------
    def _last_user_text(self, body: dict) -> str:
        for m in reversed(body.get("messages") or []):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return " ".join(p.get("text", "") for p in c
                                    if isinstance(p, dict) and p.get("type") == "text")
        return ""

    def _connect_card(self, user_email: str) -> str:
        url = (f"{self.valves.public_base_url}/gmail/auth/google/start"
               f"?user_email={user_email}")
        return (
            '<div style="padding:16px;background:linear-gradient(135deg,#1e3a5f,#2d5a87);'
            'border-radius:12px;color:#fff;margin:6px 0 14px 0;">'
            '<h3 style="margin:0 0 6px 0;">\U0001F517 Connect your Gmail</h3>'
            '<p style="margin:0 0 12px 0;opacity:0.9;">Link your Google account so I '
            'can draft emails for you right here. Drafts are saved to your Gmail '
            'Drafts, never sent automatically.</p>'
            f'<a href="{url}" target="_blank" rel="noopener" '
            'style="display:inline-block;padding:12px 22px;background:#4CAF50;color:#fff;'
            'text-decoration:none;border-radius:8px;font-weight:bold;">Connect Gmail</a>'
            f'<p style="margin:10px 0 0 0;font-size:12px;opacity:0.7;">Connecting as '
            f'{user_email}. After you approve, ask me again.</p></div>\n\n'
            f'If the button does not open, use this link: {url}'
        )

    async def _connected(self, user_email: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                r = await client.get(f"{self.valves.gmail_url}/auth/status",
                                     headers={"X-User-Email": user_email})
            return bool(r.json().get("connected")) if r.status_code == 200 else False
        except Exception:
            return False

    async def _extract(self, text: str) -> Optional[dict]:
        key = _first_sk(self.valves.openai_api_key or os.environ.get("OPENAI_API_KEY", ""))
        if not key:
            return None
        sys = ("Extract email fields from the user's request. Return ONLY compact "
               "JSON with keys to, subject, body. 'to' is the recipient email "
               "address (empty string if none is given). Write a natural, complete "
               "email body. No markdown, no code fences.")
        payload = {
            "model": self.valves.extract_model,
            "messages": [{"role": "system", "content": sys},
                         {"role": "user", "content": text}],
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                r = await client.post(OPENAI_URL, json=payload,
                                      headers={"Authorization": f"Bearer {key}"})
            if r.status_code != 200:
                return None
            content = r.json()["choices"][0]["message"].get("content") or ""
            content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def _create_draft(self, user_email, to, subject, body) -> dict:
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
            r = await client.post(
                f"{self.valves.gmail_url}/gmail_create_draft",
                json={"to": to, "subject": subject, "body": body},
                headers={"X-User-Email": user_email})
            return r.json()

    # --- entrypoint ------------------------------------------------------
    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        user_email = (__user__ or {}).get("email") or ""
        if not user_email:
            return "I couldn't identify your account. Please sign in again."

        if not await self._connected(user_email):
            return self._connect_card(user_email)

        text = self._last_user_text(body)
        if not text.strip():
            return ("Your Gmail is connected. Tell me who to email and what to say, "
                    "for example: \"email jane@acme.com about Friday, say I'll be "
                    "10 minutes late.\"")

        fields = await self._extract(text)
        if not fields or not (fields.get("to") or "").strip():
            return ("Who should I email? Give me a recipient and what to say, e.g. "
                    "\"email jane@acme.com, subject Hello, say hi.\"")

        result = await self._create_draft(
            user_email, fields["to"], fields.get("subject", ""), fields.get("body", ""))
        if isinstance(result, dict) and result.get("error"):
            return f"{result['error']}\n\n{self._connect_card(user_email)}"

        subject = fields.get("subject", "") or "(no subject)"
        body_preview = (fields.get("body", "") or "").strip()
        return (
            "✅ **Draft saved to your Gmail Drafts** (nothing was sent).\n\n"
            f"- **To:** {fields['to']}\n"
            f"- **Subject:** {subject}\n\n"
            f"**Body:**\n\n{body_preview}\n\n"
            "Open Gmail to review and send it, or tell me what to change."
        )
