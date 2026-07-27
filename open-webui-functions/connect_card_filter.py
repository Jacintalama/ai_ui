"""
title: Connect Gmail & Drive Card
author: AIUI Team
version: 0.1.0
description: When you mention email or Google Drive and your account isn't linked yet, this drops a one-click Connect card right into the chat, no need for the model to decide to do it.
"""

# Deterministic connect UX. Runs as a GLOBAL filter on every chat, so it does
# not depend on the model choosing to call a tool. In outlet (after the model
# replies) it checks the user's last message for email / Drive intent; if the
# user's Google account for that service is not connected, it prepends a styled
# Connect card (Open WebUI renders the inline HTML) to the reply. Once the user
# is connected, the card stops appearing.

from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, Field

GMAIL_WORDS = ("gmail", "email", "e-mail", "inbox", "compose an email",
               "draft an email", "send an email")
GDRIVE_WORDS = ("google drive", "gdrive", "my drive", "save to drive",
                "to my drive", "on my drive", "drive folder")


class Filter:
    class Valves(BaseModel):
        gmail_url: str = Field(default="http://mcp-gmail:8000")
        gdrive_url: str = Field(default="http://mcp-gdrive:8000")
        public_base_url: str = Field(default="https://ai-ui.coolestdomain.win")
        timeout_seconds: int = Field(default=8)

    def __init__(self):
        self.valves = self.Valves()

    # --- pure helpers (unit tested) --------------------------------------
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

    def detect_service(self, text: str) -> Optional[str]:
        low = (text or "").lower()
        if any(w in low for w in GDRIVE_WORDS):
            return "gdrive"
        if any(w in low for w in GMAIL_WORDS):
            return "gmail"
        return None

    def _connect_url(self, service: str, user_email: str) -> str:
        seg = "gdrive" if service == "gdrive" else "gmail"
        return (f"{self.valves.public_base_url}/{seg}/auth/google/start"
                f"?user_email={user_email}")

    def build_card(self, service: str, user_email: str) -> str:
        if service == "gdrive":
            title, blurb, label = ("Connect your Google Drive",
                                   "Link your Google account to save and read files right here in chat.",
                                   "Connect Google Drive")
        else:
            title, blurb, label = ("Connect your Gmail",
                                   "Link your Google account to draft and manage email right here in chat.",
                                   "Connect Gmail")
        url = self._connect_url(service, user_email)
        return (
            '<div style="padding:16px;background:linear-gradient(135deg,#1e3a5f,#2d5a87);'
            'border-radius:12px;color:#fff;margin:6px 0 14px 0;">'
            f'<h3 style="margin:0 0 6px 0;">\U0001F517 {title}</h3>'
            f'<p style="margin:0 0 12px 0;opacity:0.9;">{blurb}</p>'
            f'<a href="{url}" target="_blank" rel="noopener" '
            'style="display:inline-block;padding:12px 22px;background:#4CAF50;color:#fff;'
            'text-decoration:none;border-radius:8px;font-weight:bold;">'
            f'{label}</a>'
            f'<p style="margin:10px 0 0 0;font-size:12px;opacity:0.7;">'
            f'Connecting as {user_email}. After you approve, just ask again.</p>'
            '</div>\n\n'
        )

    def _prepend(self, body: dict, card: str) -> dict:
        msgs = body.get("messages") or []
        if msgs and isinstance(msgs[-1], dict) and msgs[-1].get("role") == "assistant":
            msgs[-1]["content"] = card + (msgs[-1].get("content") or "")
        return body

    # --- OWUI hooks -------------------------------------------------------
    async def _connected(self, service: str, user_email: str) -> bool:
        url = self.valves.gdrive_url if service == "gdrive" else self.valves.gmail_url
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                r = await client.get(f"{url}/auth/status",
                                     headers={"X-User-Email": user_email})
            return bool(r.json().get("connected")) if r.status_code == 200 else False
        except Exception:
            # On any error, assume not connected so we still offer the link.
            return False

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        print(f"[connect_card] inlet fired; user={(__user__ or {}).get('email')}", flush=True)
        return body

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> dict:
        text = self._last_user_text(body)
        service = self.detect_service(text)
        user_email = (__user__ or {}).get("email") or ""
        print(f"[connect_card] outlet fired; user={user_email!r} "
              f"service={service!r} emitter={bool(__event_emitter__)} "
              f"text={text[:60]!r}", flush=True)
        if not service:
            return body
        if not user_email:
            print("[connect_card] no user_email; skipping", flush=True)
            return body
        connected = await self._connected(service, user_email)
        print(f"[connect_card] connected({service},{user_email})={connected}", flush=True)
        if connected:
            return body  # already linked; leave the model's answer alone
        card = self.build_card(service, user_email)
        # Live render: emit the card so it shows immediately in the open chat.
        if __event_emitter__:
            try:
                await __event_emitter__({"type": "message", "data": {"content": "\n\n" + card}})
                print("[connect_card] emitted card via event_emitter", flush=True)
                return body  # emitted content is persisted by OWUI; avoid doubling
            except Exception as e:
                print(f"[connect_card] emit failed ({e}); falling back to body", flush=True)
        # No emitter (or emit failed): mutate the body so it persists at least.
        print("[connect_card] prepending card into body", flush=True)
        return self._prepend(body, card)
