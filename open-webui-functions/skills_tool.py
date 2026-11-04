"""
title: Skills
author: AIUI Team
version: 0.2.0
description: Find a ready-made procedure for a job and follow it, or write a new one when nothing fits. Ask "is there a skill for X", or "write me a skill for chasing invoices".
"""

# Native Open WebUI tool. Talks to the tasks service, which holds the skill
# library on disk.
#
# Why this exists, in numbers measured on 2026-09-10: there are 64 skills,
# their bodies total 37,990 characters, and an agent's brief can carry about
# 8,000. So an agent can hold roughly 13 of them, and the other 51 are
# unreachable unless somebody predicted in advance which ones would be needed
# and ticked the boxes.
#
# This is the same idea as vercel-labs/find-skills, the most installed skill
# on the public marketplace, reshaped for a platform where agents have no
# shell and no filesystem. There is nothing to install: the library is already
# here, and what was missing was a way to reach past the ticked few.
#
# The cost is one sentence in every brief saying the tool exists, rather than
# 10,858 characters of catalogue.

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default="http://tasks:8210")
        timeout_seconds: int = Field(default=20)

    def __init__(self):
        self.valves = self.Valves()

    async def _get(self, path: str, params: dict, email: str):
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
            return await c.get(f"{self.valves.tasks_url}{path}",
                               params=params,
                               headers={"X-User-Email": email})

    async def _post(self, path: str, payload: dict, email: str):
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
            return await c.post(f"{self.valves.tasks_url}{path}",
                                json=payload,
                                headers={"X-User-Email": email})

    async def find_skills(self, query: str, __user__: dict = {}) -> str:
        """
        Find ready-made instructions for a job. Use whenever the user asks for
        something that sounds like a recurring task, or asks whether you can do
        something, or says "is there a skill for...". Search before improvising:
        a skill is a worked procedure and your own guess is not.

        :param query: What the user wants done, in their own words. "chase
            unpaid invoices", "sort my inbox", "write a proposal".
        :return: The matching skills and what each one is for, or a sentence
            saying nothing matched.
        """
        email = (__user__ or {}).get("email", "")
        try:
            r = await self._get("/agents/skills/find", {"q": query}, email)
        except Exception as e:                              # noqa: BLE001
            return f"Could not search the skills just now: {e}"
        if r.status_code != 200:
            return "Could not search the skills just now."
        data = r.json() or {}
        hits = data.get("skills") or []
        if not hits:
            return (f"No skill matches {query!r}, out of "
                    f"{data.get('total', 0)}. Do the job yourself and say you "
                    "had no ready-made procedure for it.")
        lines = [f"{len(hits)} of {data.get('total', 0)} skills match. "
                 "Call use_skill with the name of the one that fits, then "
                 "follow it exactly."]
        for s in hits:
            needs = ", ".join(s.get("tools") or [])
            lines.append(f"- {s['name']}: {s['description']}"
                         + (f" (needs {needs})" if needs else ""))
        return "\n".join(lines)

    async def use_skill(self, name: str, __user__: dict = {}) -> str:
        """
        Read the instructions for one skill and follow them for this task. Call
        this after find_skills has told you which one fits. Follow what comes
        back exactly, in preference to your own general approach.

        :param name: The exact skill name from find_skills, such as
            "inbox-triage".
        :return: The instructions, or a sentence saying there is no such skill.
        """
        email = (__user__ or {}).get("email", "")
        try:
            r = await self._get("/agents/skills/body", {"name": name}, email)
        except Exception as e:                              # noqa: BLE001
            return f"Could not read that skill just now: {e}"
        if r.status_code == 404:
            return (f"There is no skill called {name!r}. Run find_skills "
                    "again and use a name exactly as it was given.")
        if r.status_code != 200:
            return "Could not read that skill just now."
        body = (r.json() or {}).get("body") or ""
        if not body:
            return f"The skill {name!r} has no instructions."
        return ("Follow these instructions for this task, in preference to "
                f"your own general approach:\n\n{body}")

    # --- writing one when nothing fits (2026-11-04) ----------------------
    # The platform ships 68 skills and, until this, somebody whose job none
    # of them covered needed a pull request and a deploy.
    #
    # Two calls on purpose. A skill is pasted into every turn of every agent
    # holding it, so a model must not be able to install instructions the
    # person has not read. write_skill shows one and saves nothing;
    # save_skill saves exactly what was shown.

    async def write_skill(self, job: str, __user__: dict = {}) -> str:
        """
        Write a new skill for a job that no existing skill covers. Use after
        find_skills has come back with nothing that fits, or when the user
        asks for a skill to be written or created.

        This SAVES NOTHING. It writes one and shows it. Show the user what
        comes back, in full, and tell them to say yes if they want it kept.

        :param job: The job, in the user's own words. "chase unpaid
            invoices", "write the Monday update".
        :return: The drafted skill and the code that saves it.
        """
        email = (__user__ or {}).get("email", "")
        try:
            r = await self._post("/agents/skills/draft", {"job": job}, email)
        except Exception as e:                              # noqa: BLE001
            return f"Could not write that skill just now: {e}"
        if r.status_code == 422:
            return ((r.json() or {}).get("detail")
                    or "I could not write that one. Try saying the job in a sentence.")
        if r.status_code != 200:
            return "Could not write that skill just now."
        d = r.json() or {}
        needs = ", ".join(d.get("tools") or [])
        lines = ["Here is the skill I would save. Nothing has been saved yet.",
                 "",
                 f"Name: {d.get('name', '')}",
                 f"What it is for: {d.get('description', '')}"]
        if needs:
            lines.append(f"Tools it uses: {needs}")
        if d.get("warning"):
            lines.append(d["warning"])
        lines += ["", "Instructions:", d.get("body", ""), "",
                  "If that is right, say so and I will save it. Tell me what "
                  "to change and I will write it again.",
                  f"(confirm code: {d.get('confirm', '')})"]
        return chr(10).join(lines)

    async def save_skill(self, confirm: str, __user__: dict = {}) -> str:
        """
        Save the skill that write_skill just showed. Call this only after the
        user has seen it and said yes.

        :param confirm: The confirm code from write_skill, exactly as given.
        :return: Whether it was saved.
        """
        email = (__user__ or {}).get("email", "")
        try:
            r = await self._post("/agents/skills/mine",
                                 {"confirm": (confirm or "").strip()}, email)
        except Exception as e:                              # noqa: BLE001
            return f"Could not save that skill just now: {e}"
        if r.status_code in (409, 422):
            return (r.json() or {}).get("detail") or "That skill was not saved."
        if r.status_code != 200:
            return "Could not save that skill just now."
        d = r.json() or {}
        out = (f"Saved {d.get('name', 'it')}. It is in your skills now, and "
               "you can tick it on any of your agents.")
        return out + (" " + d["warning"] if d.get("warning") else "")
