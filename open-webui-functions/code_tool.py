"""
title: Your Code
author: Ralph Benitez
version: 1.0.0
description: Lets an agent read the apps you built here, and change one after you approve exactly what it would do.
requirements: httpx
"""
# Holds no logic on purpose, the same as agents_tool.py and account_tool.py:
# the tasks service decides membership, which paths are readable, and
# whether an approval code is still good. Keeping those decisions in one
# place is what makes the web chat, Discord and Telegram behave the same,
# and it is what makes an agent's access level apply here too.
import os

import httpx
from pydantic import BaseModel, Field

#: How a refusal reads when the service declined. The service writes the
#: reason; this is only the wrapper around it.
REFUSED = "That was not allowed: "


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        internal_secret: str = Field(
            default=os.environ.get("INTERNAL_CALLBACK_SECRET", ""))
        timeout_seconds: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        url = self.valves.tasks_url.rstrip("/") + path
        headers = {"X-Internal-Secret": self.valves.internal_secret}
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
            if method == "GET":
                r = await c.get(url, headers=headers, params=kwargs)
            else:
                r = await c.post(url, headers=headers, json=kwargs)
            if r.status_code >= 400:
                body = {}
                try:
                    body = r.json()
                except ValueError:
                    pass
                detail = body.get("detail") if isinstance(body, dict) else None
                raise RuntimeError(detail or ("the service returned "
                                              + str(r.status_code)))
            data = r.json()
            return data if isinstance(data, dict) else {}

    def _email(self, user) -> str:
        email = (user or {}).get("email") or ""
        if not email:
            raise RuntimeError("I could not tell whose account this is.")
        return email

    async def list_my_apps(self, __user__: dict = {}) -> str:
        """
        List the apps this person built on this platform. Call this first
        when they ask about "my site", "my app" or a page of theirs, so you
        know which slug to use for the other calls.
        """
        try:
            data = await self._call("GET", "/code/apps",
                                    user_email=self._email(__user__))
        except RuntimeError as exc:
            return REFUSED + str(exc)
        apps = data.get("apps") or []
        if not apps:
            return "This person has not built any apps here yet."
        return "Their apps: " + ", ".join(apps)

    async def read_app_file(self, slug: str, path: str,
                            __user__: dict = {}) -> str:
        """
        Read one file from one of this person's apps. `slug` is the app,
        `path` is relative to the app, for example "src/Checkout.tsx". Use
        search_my_app first if you do not already know the path.
        """
        try:
            data = await self._call("GET", "/code/file",
                                    user_email=self._email(__user__),
                                    slug=slug, path=path)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        return slug + "/" + path + ":\n\n" + (data.get("text") or "")

    async def search_my_app(self, slug: str, query: str,
                            __user__: dict = {}) -> str:
        """
        Find where some text appears in one of this person's apps. Use this
        to locate a page or a component before reading it, rather than
        guessing a filename.
        """
        try:
            data = await self._call("GET", "/code/search",
                                    user_email=self._email(__user__),
                                    slug=slug, query=query)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        matches = data.get("matches") or []
        if not matches:
            return "Nothing in " + slug + " matches that."
        lines = [m.get("path", "") + ":" + str(m.get("line", "")) + "  "
                 + (m.get("text") or "") for m in matches]
        return "Matches in " + slug + ":\n" + "\n".join(lines)

    async def propose_app_change(self, slug: str, description: str,
                                 __user__: dict = {}) -> str:
        """
        Describe a change you want to make to one of this person's apps.
        This changes NOTHING. It returns an approval code.

        Say plainly what you would change and which file, then show the
        person the approval code and ask them to confirm. Only call
        apply_app_change once they have said yes in their own words.
        """
        try:
            data = await self._call("POST", "/code/propose",
                                    user_email=self._email(__user__),
                                    slug=slug, description=description)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        return ("Nothing has changed yet. Ask them to confirm this, then "
                "call apply_app_change with the code.\n"
                "App: " + slug + "\nChange: " + (data.get("description") or "")
                + "\nApproval code: " + (data.get("token") or ""))

    async def apply_app_change(self, token: str, __user__: dict = {}) -> str:
        """
        Carry out a change the person has just approved, using the approval
        code from propose_app_change. Only call this after they have
        actually agreed. The code works once.
        """
        try:
            data = await self._call("POST", "/code/apply",
                                    user_email=self._email(__user__),
                                    token=token)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        return ("Started. " + (data.get("slug") or "The app")
                + " is being changed: " + (data.get("description") or "")
                + ". It is smoke tested afterwards and rolled back "
                  "automatically if it breaks.")
