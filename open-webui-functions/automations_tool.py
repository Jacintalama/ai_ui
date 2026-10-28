"""
title: Automations
author: Ralph Benitez
version: 1.0.0
description: Set up rules from the chat: when something posts to a rule's URL, one of your agents does what you said and the answer goes where you chose. List, pause, resume, run or delete your rules.
requirements: httpx
"""
# Holds no secret, the way agent_builder_tool.py and schedules_tool.py do: it
# sends the caller's email and nothing else, and every route it calls on the
# tasks service is scoped to that email. A model cannot name the user, so it
# cannot act as another one.
#
# Time is not a trigger here. "Every Monday at nine" is a schedule, and the
# Schedules tool makes those; this tool says so when asked for one.
import os

import httpx
from pydantic import BaseModel, Field

DELIVERIES = {"chat": "in the agent's chat", "discord": "in your Discord thread",
              "none": "only to whoever calls the URL"}


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------ plumbing

    def _email(self, __user__: dict) -> str:
        user = __user__ if isinstance(__user__, dict) else {}
        return str(user.get("email") or "").strip()

    async def _call(self, method: str, path: str, email: str, json_body: dict = None):
        """One request as this person. Returns (ok, data) or (False, sentence).
        Never raises and never includes the exception text."""
        url = self.valves.tasks_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                response = await client.request(method, url, headers={"X-User-Email": email},
                                                json=json_body)
                if not response.is_success:
                    return False, self._refusal(response)
                return True, (response.json() if response.content else {})
        except Exception:                                   # noqa: BLE001
            return False, "I could not reach your automations just now."

    def _refusal(self, response) -> str:
        if response.status_code < 500:
            try:
                detail = response.json().get("detail")
            except Exception:                               # noqa: BLE001
                detail = None
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return "I could not reach your automations just now."

    async def _rules(self, email: str):
        ok, data = await self._call("GET", "/api/tasks/automations", email)
        if not ok:
            return None, data
        return [a for a in (data.get("automations") or []) if isinstance(a, dict)], ""

    def _find(self, rules: list, name: str):
        want = (name or "").strip().lower()
        if not want:
            return None
        exact = [a for a in rules if str(a.get("name") or "").lower() == want
                 or str(a.get("id") or "").lower() == want]
        if len(exact) == 1:
            return exact[0]
        loose = [a for a in rules if want in str(a.get("name") or "").lower()]
        return loose[0] if len(loose) == 1 else None

    def _describe(self, a: dict) -> str:
        return ("%s: %s, answers %s%s" % (
            a.get("name"), a.get("agent_name") or a.get("agent_id"),
            DELIVERIES.get(a.get("deliver_to"), a.get("deliver_to")),
            "" if a.get("enabled", True) else " (paused)"))

    # --------------------------------------------------------------------- tools

    async def list_my_automations(self, __user__: dict = {}) -> str:
        """List the automations this person has: rules that run one of their
        agents when something posts to the rule's URL. Use this before
        making, pausing or deleting one."""
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot list your automations."
        rules, why = await self._rules(email)
        if rules is None:
            return why
        if not rules:
            return ("You have no automations yet. I can make one: tell me what "
                    "should happen, which agent should do it, and where the "
                    "answer should go.")
        return "Your automations: " + "; ".join(self._describe(a) for a in rules) + "."

    async def create_automation(self, name: str, agent: str, instructions: str,
                                deliver_to: str = "chat", __user__: dict = {}) -> str:
        """Make an automation: a rule with its own URL. When anything posts
        to that URL (a website form, Zapier, n8n, a GitHub webhook, a phone
        shortcut), the agent does what `instructions` says with what was
        posted, and the answer goes to `deliver_to`. Use this when the
        person says "when X happens, have Y do Z" or "every time a lead
        comes in". NOT for anything on a timer ("every Monday at nine",
        "each morning"): that is a schedule, made with the Schedules tool.
        `name` is short, as they would recognise it ("New website lead").
        `agent` is the name of one of their agents. `instructions` is what
        the agent should do each time, in plain sentences. `deliver_to` is
        chat (the agent's chat in the office), discord (their Discord
        thread) or none (only the caller of the URL gets the answer); use
        chat unless they said otherwise. The person then puts the URL where
        the thing happens."""
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot make an automation."
        ok, data = await self._call("POST", "/api/tasks/automations", email, {
            "name": (name or "").strip(), "agent": (agent or "").strip(),
            "instructions": (instructions or "").strip(),
            "deliver_to": (deliver_to or "chat").strip().lower()})
        if not ok:
            return "Nothing was made: " + data
        return ("Made the automation %s. %s will do that whenever something posts "
                "to this URL, and the answer goes %s:\n%s\nPut the URL where the "
                "thing happens: a form, Zapier, n8n, a GitHub webhook or a phone "
                "shortcut. Only an agent set to All changes things on such a run; "
                "the others read and answer." % (
                    data.get("name", name), data.get("agent_name") or agent,
                    DELIVERIES.get(data.get("deliver_to"), data.get("deliver_to")),
                    data.get("hook_url", "")))

    async def _set_enabled(self, name: str, enabled: bool, __user__: dict) -> str:
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot change your automations."
        rules, why = await self._rules(email)
        if rules is None:
            return why
        rule = self._find(rules, name)
        if rule is None:
            return "I could not tell which automation you mean. " + (
                "You have: " + "; ".join(a.get("name", "") for a in rules) + "."
                if rules else "You have none yet.")
        ok, data = await self._call("PATCH", "/api/tasks/automations/" + str(rule["id"]),
                                    email, {"enabled": enabled})
        if not ok:
            return "Nothing changed: " + data
        return ("Paused %s. Its URL answers nothing until you resume it."
                if not enabled else "Resumed %s. Its URL works again.") % rule.get("name")

    async def pause_automation(self, name: str, __user__: dict = {}) -> str:
        """Pause one of this person's automations by name. Its URL stops
        working until it is resumed; nothing is deleted."""
        return await self._set_enabled(name, False, __user__)

    async def resume_automation(self, name: str, __user__: dict = {}) -> str:
        """Resume a paused automation by name."""
        return await self._set_enabled(name, True, __user__)

    async def delete_automation(self, name: str, __user__: dict = {}) -> str:
        """Delete one of this person's automations by name. Its URL stops
        working at once and its runs are gone. Pause instead unless they
        said delete."""
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot delete an automation."
        rules, why = await self._rules(email)
        if rules is None:
            return why
        rule = self._find(rules, name)
        if rule is None:
            return "I could not tell which automation you mean. " + (
                "You have: " + "; ".join(a.get("name", "") for a in rules) + "."
                if rules else "You have none yet.")
        ok, data = await self._call("DELETE", "/api/tasks/automations/" + str(rule["id"]), email)
        if not ok:
            return "Nothing was deleted: " + data
        return "Deleted %s. Its URL no longer works." % rule.get("name")

    async def run_automation(self, name: str, note: str = "", __user__: dict = {}) -> str:
        """Run one of this person's automations now, by name, as a test or
        by hand. `note` is optional text handed to the agent as what
        happened. Returns the agent's answer."""
        email = self._email(__user__)
        if not email:
            return "I do not know who is asking, so I cannot run an automation."
        rules, why = await self._rules(email)
        if rules is None:
            return why
        rule = self._find(rules, name)
        if rule is None:
            return "I could not tell which automation you mean. " + (
                "You have: " + "; ".join(a.get("name", "") for a in rules) + "."
                if rules else "You have none yet.")
        payload = {"note": note.strip()} if (note or "").strip() else {"test": True}
        ok, data = await self._call("POST", "/api/tasks/automations/" + str(rule["id"]) + "/run",
                                    email, {"payload": payload})
        if not ok:
            return "It did not run: " + data
        answer = str(data.get("answer") or "").strip()
        notes = [n for n in (data.get("notes") or []) if isinstance(n, str)]
        if data.get("status") != "done":
            return "%s did not finish: %s" % (rule.get("name"), " ".join(notes) or "no reason given")
        where = DELIVERIES.get(rule.get("deliver_to"), rule.get("deliver_to"))
        return "%s ran. The answer went %s.%s" % (
            rule.get("name"), where,
            ("\n\n" + answer) if answer else "") + (("\n" + "\n".join(notes)) if notes else "")
