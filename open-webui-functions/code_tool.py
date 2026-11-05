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
BROKE = ("Something went wrong on the service side and I cannot tell "
        "whether it went through: ")


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

    async def _call(self, method: str, route: str, /, **kwargs) -> dict:
        # method and route are positional-only. read_app_file's own query
        # parameter is called "path", which once collided with a
        # same-named positional parameter here; a future request field
        # named "method" or "route" would reproduce that exact bug if
        # either could still be passed by keyword.
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

    @staticmethod
    def _agent(model) -> str | None:
        """The calling agent's id, as the tool runner filled it in. The
        service reads that agent's design skill from it, so a build started
        by an agent with Impeccable ticked is built with Impeccable."""
        value = model.get("id") if isinstance(model, dict) else None
        return value if isinstance(value, str) and value else None

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

    async def create_app(self, description: str, name: str = "",
                         __model__: dict = {}, __user__: dict = {}) -> str:
        """
        Build a NEW app, site or page for this person from a description.

        Use this when what they asked for does not exist yet. Every other
        tool here works on an app that is already there, so without this the
        only honest answer to "build me a landing page" is a list of apps
        that are not the one they wanted.

        Do not ask them to pick an existing app first. Do not ask for an
        approval code either; there is nothing yet to overwrite. Say what you
        are building and build it.

        Do NOT write a link or a URL of any kind. The page shows the build
        as it happens and the finished site in the reply itself, so a link
        is clutter pointing at something already on screen.

        The result ends with a line starting "[aiui-artifact]". Copy that
        line into your reply exactly as written, on its own line at the end.
        It renders as nothing; it is how the page knows which build to show.
        """
        try:
            data = await self._call("POST", "/code/create",
                                    user_email=self._email(__user__),
                                    description=description,
                                    name=(name or "").strip() or None,
                                    agent_id=self._agent(__model__))
        except RuntimeError as exc:
            return self._message(exc)
        said = ("Building " + (data.get("slug") or "the app")
                + " now: " + (description or "").strip()
                + ". It takes a few minutes, and it is smoke tested when it "
                  "finishes and rolled back automatically if it breaks.")
        # DECLARED, not linked. The page draws the build itself: the
        # steps it is walking, and the site when it is done. A URL in the
        # reply is a second way to see the same thing, and it is the worse
        # one, so this says WHICH build in a line markdown renders as
        # nothing at all.
        task_id = str(data.get("task_id") or "")
        if task_id:
            said += "\n\n[aiui-artifact]: #build/" + task_id
        return said

    async def build_status(self, task_id: str, __user__: dict = {}) -> str:
        """
        Say how a build is getting on, using the id from create_app.

        Use this whenever they ask whether it is done, or before you tell
        them an app is ready. A build runs for minutes after you answer, so
        without checking, the first thing they learn about a failure is a red
        badge on a card they had to go and find.
        """
        try:
            data = await self._call("GET", "/code/build",
                                    user_email=self._email(__user__),
                                    task_id=task_id)
        except RuntimeError as exc:
            return self._message(exc)
        status = str(data.get("status") or "")
        slug = str(data.get("slug") or "the app")
        if status == "completed":
            said = slug + " is built."
            # The app itself goes in the reply, so the slug is declared
            # rather than a link offered to go and look at it elsewhere.
            named = str(data.get("slug") or "")
            if named:
                said += "\n\n[aiui-artifact]: #app/" + named
            return said
        if status == "failed":
            # The reason as the platform recorded it. Today that is often a
            # billing refusal from the model provider, which is something the
            # owner can act on and nothing an agent can retry around.
            why = str(data.get("error") or "").strip()
            return (slug + " failed to build."
                    + ("\n" + why if why else ""))
        if status == "needs_input":
            question = str(data.get("question") or "").strip()
            return (slug + " is waiting on an answer."
                    + ("\n" + question if question else ""))
        return slug + " is still building."

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

    async def apply_app_change(self, token: str, __model__: dict = {},
                               __user__: dict = {}) -> str:
        """
        Carry out a change the person has just approved, using the approval
        code from propose_app_change. Only call this after they have
        actually agreed. The code works once.

        Do NOT write a link or a URL. The page shows the change happening
        and the finished site in the reply itself.

        The result ends with a line starting "[aiui-artifact]". Copy that
        line into your reply exactly as written, on its own line at the end.
        It renders as nothing; it is how the page knows which build to show.
        """
        try:
            data = await self._call("POST", "/code/apply",
                                    user_email=self._email(__user__),
                                    token=token,
                                    agent_id=self._agent(__model__))
        except RuntimeError as exc:
            return self._message(exc)
        said = ("Started. " + (data.get("slug") or "The app")
                + " is being changed: " + (data.get("description") or "")
                + ". It is smoke tested afterwards and rolled back "
                  "automatically if it breaks.")
        # Declared, not linked, like create_app: a change is a build and
        # the page walks it in the reply.
        task_id = str(data.get("task_id") or "")
        if task_id:
            said += "\n\n[aiui-artifact]: #build/" + task_id
        return said
