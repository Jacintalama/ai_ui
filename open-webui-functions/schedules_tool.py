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

    # --------------------------------------------------------------- writing

    async def _timezone_for(self, email: str):
        """(zone, detected) for this person.

        /prefs/timezone always returns a zone plus a `detected` flag, so a
        caller never has to know what the platform default is. A failed read
        is not a reason to refuse a schedule, only a reason to say which zone
        was used.
        """
        ok, data = await self._call("GET", "/prefs/timezone", email)
        if not ok or not isinstance(data, dict):
            return "", False
        zone = data.get("timezone")
        return (str(zone) if zone else ""), bool(data.get("detected"))

    def _agent_id_from(self, __model__: dict):
        """The agent making this call, when the caller IS an agent.

        A schedule an agent creates should run as that agent. But this tool
        is on every model, and "gpt-5" is not one of this person's agents:
        sending it as agent_id would make a schedule that can never run. Only
        an id shaped like one this platform mints is passed on.
        """
        model_id = str((__model__ or {}).get("id") or "")
        return model_id if model_id.startswith("agent-") else None

    async def create_schedule(self, name: str, cron_expr: str, prompt: str,
                              __user__: dict = {}, __model__: dict = {}) -> str:
        """
        Put something on this person's schedule, so it runs by itself from
        now on.

        Call this when they ask for something to happen regularly or at a
        set time: "check my inbox every morning at eight", "remind me on
        Fridays", "run this every hour".

        :param name: A short name they will recognise on their Cron Jobs
            page, e.g. "Morning inbox".
        :param cron_expr: Five-field cron. "0 8 * * *" is every day at eight
            in the morning. "0 9 * * 1" is nine on Mondays. "0 * * * *" is
            hourly.
        :param prompt: What should happen when it runs, written as an
            instruction, e.g. "list my unread email and say what needs a
            reply today".
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule this is, so I did not make one."

        zone, detected = await self._timezone_for(email)
        body = {"name": name, "cron_expr": cron_expr, "prompt": prompt,
                "agent_id": self._agent_id_from(__model__)}
        if zone:
            body["tz"] = zone

        ok, data = await self._call("POST", "/schedules", email, body)
        if not ok:
            return "I could not put that on your schedule just now, so nothing was made."
        if not isinstance(data, dict) or not data.get("id"):
            return "Your schedule may not have been made: the reply did not name one."

        said = "Done. " + self._describe(data) + "."
        if zone and not detected:
            said += (" I used %s, because I have no timezone recorded for you. "
                     "Tell me your zone if that is wrong." % zone)
        said += (" The result will appear on your Cron Jobs page, since this "
                 "was not made from a chat channel.")
        return said

    async def enable_schedule(self, schedule_id: str,
                              __user__: dict = {}) -> str:
        """
        Turn one of this person's schedules back on, so it runs again.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", "/schedules/%s/enable" % schedule_id, __user__,
            "turned back on")

    async def disable_schedule(self, schedule_id: str,
                               __user__: dict = {}) -> str:
        """
        Turn one of this person's schedules off, leaving it in place so it
        can be turned back on later. Prefer this to deleting when they say
        pause, stop for now, or hold off.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", "/schedules/%s/disable" % schedule_id, __user__,
            "turned off")

    async def delete_schedule(self, schedule_id: str,
                              __user__: dict = {}) -> str:
        """
        Delete one of this person's schedules for good. This cannot be
        undone, so prefer disable_schedule unless they clearly want it gone.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "DELETE", "/schedules/%s" % schedule_id, __user__, "deleted")

    async def trigger_schedule_now(self, schedule_id: str,
                                   __user__: dict = {}) -> str:
        """
        Run one of this person's schedules right now, without waiting for
        its next scheduled time. Leaves the schedule itself unchanged.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", "/schedules/%s/run-now" % schedule_id, __user__,
            "started now")

    async def _simple_write(self, method: str, path: str, __user__: dict,
                            done: str) -> str:
        """The four one-line writes, which differ only in verb, path and the
        word used to report success."""
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule that is, so I left it alone."
        ok, data = await self._call(method, path, email)
        if not ok:
            return "I could not change that schedule just now, so nothing happened."
        if isinstance(data, dict) and data.get("id"):
            return "Done, %s: %s." % (done, self._describe(data))
        return "Done, %s." % done
