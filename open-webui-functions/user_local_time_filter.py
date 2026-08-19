"""
title: User Local Time
author: Ralph Benitez
version: 0.1.0
description: Tells every model what the date and time are where you are, so "tomorrow morning" and "what time is it" mean something. Your timezone is detected automatically in your browser and is private to your account.
"""

# Global inlet filter. Runs BEFORE the model on every chat, for every model, so
# no toggle and no tool call. It puts one line in front of the conversation:
# the user's own local date, time and zone.
#
# Why this is not folded into the knowledge-graph memory filter, which already
# calls the same service on the same hook: that filter returns early when the
# message is under 3 characters and again when the graph comes back empty. Both
# are right for memory and wrong for a clock. A new user with an empty graph
# asking "hi what time is it" would get nothing. A clock has to be
# unconditional, so it gets its own filter.
#
# The zone is cached in process for 30 minutes and the timestamp is computed
# locally, so the timestamp is exact on every turn while the lookup costs about
# two requests per user per hour rather than one per message.
#
# Fails open, same contract as the memory filter: any error leaves the chat
# untouched.

import os
import time
from datetime import datetime, timezone as _tz
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

# Marker present in every line injected, so a retried request is not stamped
# twice.
_MARKER = "current local date and time is"

# The rendering below is a copy of tasks/user_timezone.py::context_line. It is
# duplicated because this file runs inside the open-webui container, which does
# not have the tasks service on its path. tasks/tests/test_owui_time_filter.py
# loads this file and asserts the two agree, so the copy cannot drift silently.
DEFAULT_TZ = os.getenv("AIUI_DEFAULT_TZ", "UTC")


def _resolved(tz_name: Optional[str]) -> Optional[str]:
    if not tz_name:
        return None
    try:
        ZoneInfo(tz_name)
    except Exception:
        return None
    return tz_name


def context_line(tz_name: Optional[str], now: Optional[datetime] = None) -> str:
    resolved = _resolved(tz_name)
    zone = resolved or DEFAULT_TZ
    moment = now or datetime.now(_tz.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_tz.utc)
    try:
        stamp = moment.astimezone(ZoneInfo(zone))
    except Exception:
        zone, stamp = "UTC", moment.astimezone(_tz.utc)
    day = str(int(stamp.strftime("%d")))
    hour = str(int(stamp.strftime("%I")))
    pretty = (f"{stamp.strftime('%A')}, {day} {stamp.strftime('%B')} "
              f"{stamp.strftime('%Y')}, {hour}:{stamp.strftime('%M %p')}")
    suffix = "" if resolved else " (zone unconfirmed, this is the platform default)"
    return (
        f"The user's current local date and time is {pretty} ({zone}){suffix}. "
        "Use this whenever the conversation involves dates, times, scheduling, "
        "or words like today, tomorrow or next week. Do not mention this note "
        "unless the time is relevant."
    )


class Filter:
    class Valves(BaseModel):
        tasks_url: str = Field(default="http://tasks:8210")
        timeout_seconds: int = Field(default=4)
        cache_seconds: int = Field(default=1800)

    def __init__(self):
        self.valves = self.Valves()
        self._zones = {}   # email -> (zone_or_None, fetched_at)

    # --- pure helpers -----------------------------------------------------
    def _already_injected(self, messages: list) -> bool:
        for m in messages:
            if (isinstance(m, dict) and m.get("role") == "system"
                    and _MARKER in (m.get("content") or "")):
                return True
        return False

    def _insert_index(self, messages: list) -> int:
        """Right after any leading system prompt(s), before the user turns."""
        idx = 0
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system":
                idx += 1
            else:
                break
        return idx

    def _cached(self, email: str, now: float):
        hit = self._zones.get(email)
        if hit and (now - hit[1]) < self.valves.cache_seconds:
            return True, hit[0]
        return False, None

    # --- I/O --------------------------------------------------------------
    async def _fetch_zone(self, user_email: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
                r = await client.get(
                    f"{self.valves.tasks_url}/prefs/timezone",
                    headers={"X-User-Email": user_email},
                )
            if r.status_code == 200:
                data = r.json() or {}
                # "detected" false means the service handed back the platform
                # default, not this user's zone. Keep that distinction so the
                # injected line can say the zone is unconfirmed.
                return data.get("timezone") if data.get("detected") else None
        except Exception as e:
            print(f"[user_local_time] fetch error: {e}", flush=True)
        return None

    # --- OWUI hook --------------------------------------------------------
    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        try:
            user_email = (__user__ or {}).get("email") or ""
            if not user_email:
                return body
            messages = body.get("messages") or []
            if self._already_injected(messages):
                return body

            now = time.time()
            hit, zone = self._cached(user_email, now)
            if not hit:
                zone = await self._fetch_zone(user_email)
                self._zones[user_email] = (zone, now)

            messages.insert(self._insert_index(messages),
                            {"role": "system", "content": context_line(zone)})
            body["messages"] = messages
        except Exception as e:
            print(f"[user_local_time] inlet error: {e}", flush=True)
        return body
