"""The user's timezone, and the sentence the assistant reads it from.

Every model on the platform had no clock. Ask one "what time is it" or "put
that in my calendar tomorrow morning" and it had no date, no time and no zone
to work from. Nothing in the service stored one.

What is stored is an IANA zone name ("Asia/Manila"), never a UTC offset. An
offset is right for half the year in any zone that observes daylight saving,
and the failure is silent: a schedule set in March quietly fires an hour off in
April. The browser reports the IANA name directly, via
Intl.DateTimeFormat().resolvedOptions().timeZone, so there is no reason to
store the weaker thing.

Pure functions only. The route layer owns the database, the Open WebUI filter
owns the injection, and both of them import from here so the rules are stated
once.
"""
from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones

#: Used when a user's zone was never detected, or was stored and later stopped
#: being a real zone. Overridable per deployment.
import os

DEFAULT_TZ = os.getenv("AIUI_DEFAULT_TZ", "UTC")

# available_timezones() walks the tzdata directory, so it is resolved once.
_KNOWN = None


def _known() -> set:
    global _KNOWN
    if _KNOWN is None:
        try:
            _KNOWN = available_timezones()
        except Exception:
            _KNOWN = {"UTC"}
    return _KNOWN


def normalise_timezone(name) -> Optional[str]:
    """An IANA zone name, or None if it is not one.

    The gate between a browser-supplied string and the database. Anything that
    is not a name tzdata recognises is refused outright rather than stored and
    dealt with later, so every value read back out is known to resolve.
    """
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned or cleaned not in _known():
        return None
    return cleaned


def should_store(stored_source: Optional[str], incoming_manual: bool) -> bool:
    """Whether an incoming zone should replace the stored one.

    Autodetect runs on page load, so without this a user who sets their zone by
    hand loses it the next time they open the app from a laptop somewhere else.
    A deliberate change always wins; a detected one only overwrites a detected
    one.
    """
    if incoming_manual:
        return True
    return (stored_source or "auto") != "manual"


def local_now(tz_name: Optional[str], now: Optional[datetime] = None) -> datetime:
    """`now` rendered in the user's zone, falling back rather than raising."""
    moment = now or datetime.now(_tz.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_tz.utc)
    for candidate in (tz_name, DEFAULT_TZ, "UTC"):
        if not candidate:
            continue
        try:
            return moment.astimezone(ZoneInfo(candidate))
        except Exception:
            continue
    return moment


def _resolved(tz_name: Optional[str]) -> Optional[str]:
    """The zone that will actually be used, or None if we fell back."""
    if not tz_name:
        return None
    try:
        ZoneInfo(tz_name)
    except Exception:
        return None
    return tz_name


def context_line(tz_name: Optional[str], now: Optional[datetime] = None) -> str:
    """The system message injected before every chat turn.

    When the zone is a fallback the line says so. A model that can see the zone
    is unconfirmed will ask; one handed a confident wrong hemisphere will not.
    """
    resolved = _resolved(tz_name)
    zone = resolved or DEFAULT_TZ
    stamp = local_now(zone, now=now)
    # %-d / %-I are not portable to Windows, so the padding is stripped by hand.
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
