"""
title: My Account
author: Ralph Benitez
version: 1.0.0
description: Checks what apps you have connected, so the assistant can offer to connect the ones you do not, with a button instead of instructions.
requirements: httpx
"""
# Read only. This is what lets the assistant say "you have no ClickUp"
# instead of guessing, and it is what replaced a regex that fired on the
# word "email" appearing anywhere in a message.
#
# The connect link it prints is a marker, not a real URL.
# mcp-servers/gdrive/integrations-ui.js finds it in the rendered answer and
# turns it into a button. That is what lets one shape serve both a vendor
# login and an API key paste, and it is why the model does not need to know
# which is which.
import os

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        internal_secret: str = Field(
            default=os.environ.get("INTERNAL_CALLBACK_SECRET", ""))
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    async def my_account(self, __user__: dict = {}) -> str:
        """
        Check which apps the user has connected to this platform, and which
        they have not. Call this whenever the user asks about connecting an
        app, asks what they have connected, or asks why an agent cannot
        reach their mail, files, or a connected service. Call it before
        offering to connect anything, so the answer is about what they
        actually have.
        """
        email = (__user__ or {}).get("email") or ""
        if not email:
            return ("I could not tell whose account this is, so I did not "
                    "check anything.")
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                r = await c.get(
                    self.valves.tasks_url.rstrip("/") + "/account/summary",
                    params={"user_email": email},
                    headers={"X-Internal-Secret": self.valves.internal_secret})
                r.raise_for_status()
                data = r.json()

            # Comes over HTTP from another service, so the shape is not ours
            # to trust: normalise before reading anything off it, the same
            # way _render in io_gateway_pipe.py does. This must stay inside
            # the try, not just the request itself, or a malformed but
            # successful response still raises past the guard below.
            data = data if isinstance(data, dict) else {}
            connected = data.get("connected")
            connected = connected if isinstance(connected, list) else []
            missing = data.get("not_connected")
            missing = missing if isinstance(missing, list) else []

            lines = []
            if connected:
                lines.append(
                    "Connected: "
                    + ", ".join(item.get("label", item.get("id", ""))
                               for item in connected if isinstance(item, dict)))
            else:
                lines.append("Nothing is connected yet.")

            if missing:
                lines.append("")
                lines.append("Not connected yet. To offer one, print its markdown "
                             "link exactly as given and say one short sentence "
                             "about what it would let them do:")
                for m in missing:
                    if not isinstance(m, dict):
                        continue
                    label = m.get("label") or m.get("id")
                    link = "[Connect %s](%s)" % (label, m.get("connect_url", ""))
                    if m.get("how") == "key":
                        lines.append("  %s  (needs an API key from %s)"
                                     % (link, m.get("where") or "that app's settings"))
                    else:
                        lines.append("  %s  (opens a login)" % link)
            return "\n".join(lines)
        except Exception:                                   # noqa: BLE001
            # Never include the exception text: an httpx error carries the
            # request URL, and this project has already leaked a token that way.
            return ("I could not check your connected apps just now. Try "
                    "again in a moment.")
