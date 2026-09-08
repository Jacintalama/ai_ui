"""
title: Schedules
author: Ralph Benitez
version: 1.0.0
description: See and manage your own scheduled runs, so an assistant can put something on your schedule instead of describing one.
requirements: httpx
"""
# This tool holds no secret, deliberately.
#
# tasks.routes_schedules._resolve_caller decides who a caller is. A request
# carrying X-Cron-Secret is an operator and may target ANY user. A request
# carrying X-User-Email and no secret is an end user, and is forced onto that
# email: the listing is filtered by it, and a create overwrites whatever
# user_email the body claimed.
#
# So this tool sends the caller's email and nothing else. The dangerous path,
# the one that can delete somebody else's schedules, needs a credential this
# file does not have and has no field to store.
import os

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(
            default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------ plumbing

    def _email(self, __user__: dict) -> str:
        """Who is asking, from Open WebUI rather than from a parameter.

        Never a method argument: a model that could name the user could act
        as another one.
        """
        return ((__user__ or {}).get("email") or "").strip()

    async def _call(self, method: str, path: str, email: str,
                    json_body: dict = None):
        """One request as this person. Returns (ok, data) or (False, sentence).

        Never raises, and never includes the exception text: an httpx error
        carries the request URL, and this project has leaked a token that way
        once.
        """
        url = self.valves.tasks_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(
                    timeout=self.valves.timeout_seconds) as client:
                response = await client.request(
                    method, url,
                    headers={"X-User-Email": email},
                    json=json_body)
                response.raise_for_status()
                return True, (response.json() if response.content else {})
        except Exception:                                   # noqa: BLE001
            return False, "I could not reach your schedules just now."

    def _describe(self, row: dict) -> str:
        """One schedule as a person reads it, not as the API returns it."""
        row = row if isinstance(row, dict) else {}
        name = str(row.get("name") or "unnamed")
        when = str(row.get("cron_expr") or "?")
        tz = str(row.get("tz") or "")
        state = "on" if row.get("enabled") else "off"
        said = '"%s" runs on %s' % (name, when)
        if tz:
            said += " (%s)" % tz
        said += ", currently %s" % state
        last = row.get("last_run_status")
        if last:
            said += ", last run %s" % str(last)
        return said + " [id %s]" % str(row.get("id") or "?")

    # --------------------------------------------------------------- reading

    async def list_my_schedules(self, __user__: dict = {}) -> str:
        """
        List this person's scheduled runs: what each one does, when it runs,
        whether it is on, and how the last run went.

        Call this whenever they ask what is scheduled, what runs
        automatically, what their cron jobs are, or whether something is
        still running. Call it before changing or deleting one, so the id you
        act on belongs to a schedule that exists.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedules these are, so I did not look."
        ok, data = await self._call("GET", "/schedules", email)
        if not ok:
            return data
        if not isinstance(data, list):
            return "Your schedules came back in a shape I did not understand."
        if not data:
            return "You have nothing scheduled."
        lines = ["You have %d scheduled:" % len(data)]
        for row in data:
            lines.append("  " + self._describe(row))
        return "\n".join(lines)
