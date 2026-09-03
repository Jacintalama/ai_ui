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

#: A refusal the service actually decided, safe to relay as one.
REFUSED = "That was not allowed: "
#: A failure the service did not choose. Deliberately does not say
#: whether anything happened, because for apply it might have: the
#: token is kept spent on an unrecognised failure exactly because work
#: may already have started.
BROKE = "I could not reach that just now, and I cannot tell whether it went through: "


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        internal_secret: str = Field(
            default=os.environ.get("INTERNAL_CALLBACK_SECRET", ""))
        timeout_seconds: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    def _broken(self, message: str) -> RuntimeError:
        """A RuntimeError marked as a failure the service did not choose,
        so the caller answers with BROKE instead of REFUSED."""
        exc = RuntimeError(message)
        exc.broke = True
        return exc

    async def _call(self, method: str, route: str, **kwargs) -> dict:
        # Named route, not path: read_app_file's own query parameter is
        # called "path", and a call passing path=path as a kwarg would
        # collide with a same-named positional parameter here.
        url = self.valves.tasks_url.rstrip("/") + route
        headers = {"X-Internal-Secret": self.valves.internal_secret}
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
                if method == "GET":
                    r = await c.get(url, headers=headers, params=kwargs)
                else:
                    r = await c.post(url, headers=headers, json=kwargs)
        except httpx.HTTPError as exc:
            # Never the exception text: an httpx error carries the URL, and the
            # read calls put the person's email in the query string. Same rule
            # as agent_tools.py.
            raise self._broken("the service did not answer ("
                               + type(exc).__name__ + ")") from exc
        if r.status_code >= 400:
            body = {}
            try:
                body = r.json()
            except ValueError:
                pass
            detail = body.get("detail") if isinstance(body, dict) else None
            # FastAPI's 422 sets detail to a list of pydantic error dicts,
            # not text meant for a person, so only a string detail is
            # relayed; anything else falls back to the plain status line.
            message = detail if isinstance(detail, str) else None
            message = message or ("the service returned " + str(r.status_code))
            if r.status_code >= 500:
                raise self._broken(message)
            raise RuntimeError(message)
        try:
            data = r.json()
        except ValueError as exc:
            raise self._broken(
                "the service answered with something unreadable") from exc
        return data if isinstance(data, dict) else {}

    def _message(self, exc: RuntimeError) -> str:
        return (BROKE if getattr(exc, "broke", False) else REFUSED) + str(exc)

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
            return self._message(exc)
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
            return self._message(exc)
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
            return self._message(exc)
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
            return self._message(exc)
        return ("Nothing has changed yet. Ask them to confirm this, then "
                "call apply_app_change with the code.\n"
                "App: " + (data.get("slug") or slug)
                + "\nChange: " + (data.get("description") or "")
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
            return self._message(exc)
        return ("Started. " + (data.get("slug") or "The app")
                + " is being changed: " + (data.get("description") or "")
                + ". It is smoke tested afterwards and rolled back "
                  "automatically if it breaks.")
