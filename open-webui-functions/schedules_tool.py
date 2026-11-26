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
#
# That argument only holds while every call this tool makes lands on
# /schedules. See _schedule_path: an id the model chose is put into a path,
# and httpx resolves dot segments before sending, so an unchecked id is a way
# to call some OTHER endpoint of the tasks service as this person.
import os
import uuid
from typing import Optional

import httpx
from pydantic import BaseModel, Field


class Tools:
    #: What routes_schedules.CreateScheduleIn falls back to when a create
    #: names no zone. Sent explicitly when this person's own zone cannot be
    #: read, so the zone they are told about is the zone that was actually
    #: sent, rather than one this tool guessed the server would pick.
    FALLBACK_TZ = "Asia/Manila"

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
        as another one. Never raises either: __user__ arrives from another
        process's plumbing, so it is not always the dict it is annotated as,
        and every method here has to return a sentence.
        """
        user = __user__ if isinstance(__user__, dict) else {}
        return str(user.get("email") or "").strip()

    def _schedule_path(self, schedule_id, suffix: str = "") -> str:
        """The path for one schedule, or "" when the id is not an id.

        This is the one place an id the model chose becomes a URL, and the
        check is not politeness. httpx resolves dot segments before sending,
        so "../connections/github" would leave /schedules entirely and, with
        this person's own X-User-Email attached, delete a different thing of
        theirs through an endpoint this tool does not declare. The endpoint
        that enforces scoping never gets a chance to help, because traversal
        changes WHICH endpoint is asked.

        Schedule ids are UUIDs. routes_schedules parses every one of them
        with uuid.UUID, so a value that is not a UUID was never a valid id,
        and refusing it here also stops a hallucinated id turning into a 500
        on the tasks service. Rebuilt from the parsed value rather than
        echoed, so only the canonical form is ever put in a path.
        """
        try:
            parsed = uuid.UUID(str(schedule_id))
        except Exception:                                   # noqa: BLE001
            return ""
        return "/schedules/" + str(parsed) + suffix

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
                # Not `>= 400`. A 301 or a 302 is not success, and reading
                # one as success would have this tell somebody their schedule
                # was deleted when the request never arrived anywhere.
                if not response.is_success:
                    return False, self._refusal(response)
                return True, (response.json() if response.content else {})
        except Exception:                                   # noqa: BLE001
            return False, "I could not reach your schedules just now."

    def _refusal(self, response) -> str:
        """What the server said, when it said something a person can act on.

        The ten-schedule cap and the fifteen-minute interval floor are
        refusals with a reason, and collapsing them into one shrug is the
        difference between an agent explaining a limit and an agent looking
        broken.

        Only below 500, and only a string `detail`: a 500 body is where an
        unhandled exception surfaces, while a `detail` under that is a
        sentence this service wrote on purpose. Neither carries the request
        URL, which is the thing that must never come back out of here.
        """
        if response.status_code < 500:
            try:
                detail = response.json().get("detail")
            except Exception:                               # noqa: BLE001
                detail = None
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return "I could not reach your schedules just now."

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
        if row.get("email_me") is True:
            said += ", its answer emailed to you"
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
        """(zone, detected) for this person, or ("", False) when unknown.

        /prefs/timezone always returns a zone plus a `detected` flag, so a
        caller never has to know what the platform default is. A read that
        fails, or answers with no zone in it, is not a reason to refuse a
        schedule. It is a reason to say which zone was used instead, and the
        empty string here is what tells create_schedule to say it.
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
        model = __model__ if isinstance(__model__, dict) else {}
        model_id = str(model.get("id") or "")
        return model_id if model_id.startswith("agent-") else None

    async def create_schedule(self, name: str, cron_expr: str, prompt: str,
                              email_me: bool = False,
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
        :param email_me: True when they asked to be emailed or sent the
            result ("email me a summary", "send me the report every
            Friday"). The platform then emails each answer to their own
            Gmail, so write the prompt as what to produce, never as "send an
            email". A cron job can only read: on its own it cannot send
            email to other people, post, or change anything. If they ask
            for that, tell them so instead of saying it is set up.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule this is, so I did not make one."

        zone, detected = await self._timezone_for(email)
        known = bool(zone)
        if not known:
            # The read failed, or answered with nothing usable. Either way
            # the zone is not this person's, so name the one that will apply
            # and send it, instead of letting the server default decide in
            # silence. A schedule an hour off looks like it worked.
            zone = self.FALLBACK_TZ
        body = {"name": name, "cron_expr": cron_expr, "prompt": prompt,
                "tz": zone, "agent_id": self._agent_id_from(__model__),
                "email_me": email_me is True}

        ok, data = await self._call("POST", "/schedules", email, body)
        if not ok:
            return "Nothing was scheduled: " + data
        if not isinstance(data, dict) or not data.get("id"):
            return "Your schedule may not have been made: the reply did not name one."

        # The create endpoint replies with only {"id": ...}, nothing else.
        # Describe what was actually made from what was actually sent, not
        # from fields read off that bare reply and defaulted to nothing.
        made = dict(body, id=data["id"], enabled=True)
        said = "Done. " + self._describe(made) + "."
        if not known:
            said += (" I could not read your timezone, so I used %s. "
                     "Tell me your zone if that is wrong." % zone)
        elif not detected:
            said += (" I used %s, because I have no timezone recorded for you. "
                     "Tell me your zone if that is wrong." % zone)
        if email_me is True:
            said += (" Its answer will be emailed to you after each run, and "
                     "will also appear on your Cron Jobs page.")
            return said
        said += (" The result will appear on your Cron Jobs page, since this "
                 "was not made from a chat channel.")
        # Live 2026-11-26 this tool said "Set up" to "email me a summary" and
        # the job could never send. Said every time, so the model cannot
        # promise an action the job will be refused.
        said += (" It runs read only: it can read the apps they connected, "
                 "but it cannot send, post or change anything by itself, so "
                 "say that if they asked it to. To have its answer emailed "
                 "to them, call update_schedule with email_me true.")
        return said

    async def update_schedule(self, schedule_id: str,
                              name: Optional[str] = None,
                              cron_expr: Optional[str] = None,
                              prompt: Optional[str] = None,
                              email_me: Optional[bool] = None,
                              __user__: dict = {}) -> str:
        """
        Change one of this person's schedules: its name, when it runs, what
        it does, or whether its answer is emailed to them. Only what you
        give changes; leave the rest out.

        Call list_my_schedules first if you do not already have the id.

        :param schedule_id: The schedule's id, from list_my_schedules.
        :param name: A new name, or leave out.
        :param cron_expr: A new five-field cron, e.g. "0 17 * * 5" for five
            on Fridays, or leave out.
        :param prompt: What it should do from now on, written as an
            instruction, or leave out.
        :param email_me: True to email each answer to their own Gmail, false
            to stop, or leave out.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule that is, so I left it alone."
        path = self._schedule_path(schedule_id)
        if not path:
            return ("That is not one of your schedule ids, so I did not touch "
                    "anything. Call list_my_schedules to see the real ones.")
        body = {}
        for key, value in (("name", name), ("cron_expr", cron_expr),
                           ("prompt", prompt)):
            if isinstance(value, str) and value.strip():
                body[key] = value
        if isinstance(email_me, bool):
            body["email_me"] = email_me
        if not body:
            return "Nothing to change was given, so I left it as it is."
        ok, data = await self._call("PATCH", path, email, body)
        if not ok:
            return "I did not change that schedule: " + data
        said = []
        if "name" in body:
            said.append('is named "%s"' % body["name"])
        if "cron_expr" in body:
            said.append("runs on %s" % body["cron_expr"])
        if "prompt" in body:
            said.append("does what it was just told")
        if body.get("email_me") is True:
            said.append("has its answer emailed to you after each run")
        elif body.get("email_me") is False:
            said.append("is no longer emailed")
        return "Done. From now on it " + ", ".join(said) + "."

    async def enable_schedule(self, schedule_id: str,
                              __user__: dict = {}) -> str:
        """
        Turn one of this person's schedules back on, so it runs again.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", schedule_id, "/enable", __user__, "turned back on")

    async def disable_schedule(self, schedule_id: str,
                               __user__: dict = {}) -> str:
        """
        Turn one of this person's schedules off, leaving it in place so it
        can be turned back on later. Prefer this to deleting when they say
        pause, stop for now, or hold off.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", schedule_id, "/disable", __user__, "turned off")

    async def delete_schedule(self, schedule_id: str,
                              __user__: dict = {}) -> str:
        """
        Delete one of this person's schedules for good. This cannot be
        undone, so prefer disable_schedule unless they clearly want it gone.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "DELETE", schedule_id, "", __user__, "deleted")

    async def trigger_schedule_now(self, schedule_id: str,
                                   __user__: dict = {}) -> str:
        """
        Run one of this person's schedules right now, without waiting for
        its next scheduled time. Leaves the schedule itself unchanged.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", schedule_id, "/run-now", __user__, "started now")

    async def _simple_write(self, method: str, schedule_id: str, suffix: str,
                            __user__: dict, done: str) -> str:
        """The four one-line writes, which differ only in verb, path suffix
        and the word used to report success.

        The id is checked here, before any path exists, because this is the
        single place all four of them build one.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule that is, so I left it alone."
        path = self._schedule_path(schedule_id, suffix)
        if not path:
            return ("That is not one of your schedule ids, so I did not touch "
                    "anything. Call list_my_schedules to see the real ones.")
        ok, data = await self._call(method, path, email)
        if not ok:
            return "I did not change that schedule: " + data
        if isinstance(data, dict) and data.get("id"):
            return "Done, %s: %s." % (done, self._describe(data))
        return "Done, %s." % done
