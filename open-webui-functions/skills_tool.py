"""
title: Skills
author: AIUI Team
version: 0.1.0
description: Let an agent find the right ready-made procedure for a job and follow it. Ask "is there a skill for X" or just ask for the job, and the agent looks it up instead of improvising.
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
