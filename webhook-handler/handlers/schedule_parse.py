"""Natural-language → cron parser for the Discord Schedules UX.

``parse_when(text)`` returns ``(cron_expr, human_readable)`` or ``None`` when
the text can't be understood as a recurring time. Pure, no I/O — unit tested
in ``tests/test_schedule_parse.py``. Non-technical users type things like
"every morning" or "every Monday 9am"; they never see cron syntax.
"""
from __future__ import annotations

import re

_DAY_NUM = {
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}
_DAY_NAME = {v: k.capitalize() for k, v in _DAY_NUM.items()}

# (lo, hi) inclusive ranges for the 5 cron fields: min hour dom month dow.
_CRON_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]

# Every schedule spawns a Claude Code agent run on a box that caps concurrency
# at 3, so the tasks API refuses anything faster than this
# (routes_schedules.MIN_INTERVAL_MINUTES — same number, separate container, no
# shared package). Enforcing it here too is not belt-and-braces: it is the
# difference between telling someone the limit and handing them a 400.
MIN_INTERVAL_MINUTES = 15

# The other half of the same cap (routes_schedules.MAX_SCHEDULES_PER_USER).
# Nothing in this service enforces it — the API owns that — but the bots quote
# it when the API says 429, so it lives beside its sibling rather than inline
# in a message string.
MAX_SCHEDULES_PER_USER = 10


def _to_24h(hour: int, ampm: str | None) -> int:
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    return hour


def _fmt_time(hour: int, minute: int) -> str:
    ampm = "AM" if hour < 12 else "PM"
    h12 = hour % 12 or 12
    return f"{h12}:{minute:02d} {ampm}"


def _valid_cron_field(field: str, lo: int, hi: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        if part.startswith("*/"):
            step = part[2:]
            if not step.isdigit() or int(step) < 1:
                return False
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                return False
            if not (lo <= int(a) <= hi and lo <= int(b) <= hi):
                return False
            continue
        if not part.isdigit() or not (lo <= int(part) <= hi):
            return False
    return True


def _is_valid_cron(s: str) -> bool:
    fields = s.split()
    if len(fields) != 5:
        return False
    return all(
        _valid_cron_field(f, lo, hi) for f, (lo, hi) in zip(fields, _CRON_RANGES)
    )


def _field_slots(field: str, lo: int, hi: int) -> list[int] | None:
    """Every value a single cron field selects, sorted. ``None`` if unreadable.

    Handles the same subset ``_valid_cron_field`` accepts: ``*``, ``*/step``,
    ``a-b`` ranges and comma lists of those.
    """
    if field == "*":
        return list(range(lo, hi + 1))
    out: set[int] = set()
    for part in field.split(","):
        if part.startswith("*/"):
            step = part[2:]
            if not step.isdigit() or int(step) < 1:
                return None
            out.update(range(lo, hi + 1, int(step)))
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                return None
            if not (lo <= int(a) <= int(b) <= hi):
                return None
            out.update(range(int(a), int(b) + 1))
            continue
        if not part.isdigit() or not (lo <= int(part) <= hi):
            return None
        out.add(int(part))
    return sorted(out)


def _has_adjacent(values: list[int], modulus: int) -> bool:
    """True when two selected values sit one apart, counting the wrap — i.e.
    the field lets one period run straight into the next."""
    if len(values) < 2:
        return False
    seen = set(values)
    return any((v + 1) % modulus in seen for v in values)


def min_gap_minutes(cron_expr: str) -> int:
    """Smallest gap between two fires, in minutes, from the minute+hour fields.

    Deliberately not a full cron simulation — no croniter in this service. It
    reads the minute field's own spacing and adds the 59 -> 00 wrap only when
    the hour field actually selects two adjacent hours, which is what makes
    `0,59 0,23 * * *` (one minute apart, at midnight) different from
    `0,59 0 * * *` (59 minutes apart, twice a day).

    Returns 60 for anything it cannot read, so an expression it does not
    understand is passed to the API rather than blocked here.
    """
    fields = cron_expr.split()
    if len(fields) != 5:
        return 60
    minutes = _field_slots(fields[0], 0, 59)
    hours = _field_slots(fields[1], 0, 23)
    if not minutes or hours is None:
        return 60
    gaps = [b - a for a, b in zip(minutes, minutes[1:])]
    if _has_adjacent(hours, 24):
        gaps.append(60 - minutes[-1] + minutes[0])
    return min(gaps) if gaps else 60


def too_frequent_error(text: str) -> str | None:
    """The reason ``parse_when`` rejected ``text``, when the reason is speed.

    ``parse_when`` returns ``None`` both for "I don't understand that" and for
    "that is faster than allowed". Call this to tell the two apart: a sentence
    naming the minimum, or ``None`` when the phrase was simply unreadable and
    the caller should keep its own "I couldn't read that" wording.
    """
    parsed = _parse_when(text)
    if parsed is None or min_gap_minutes(parsed[0]) >= MIN_INTERVAL_MINUTES:
        return None
    return (
        f"That's a bit too often — the shortest repeat is every "
        f"{MIN_INTERVAL_MINUTES} minutes. Try 'every {MIN_INTERVAL_MINUTES} "
        f"minutes', 'every hour', or 'every morning'."
    )


def parse_when(text: str) -> tuple[str, str] | None:
    """Parse a human time phrase into ``(cron_expr, human_readable)``.

    Returns ``None`` when the phrase isn't a recognizable recurring time, or
    names one faster than ``MIN_INTERVAL_MINUTES``. Use ``too_frequent_error``
    to tell those two cases apart.
    """
    parsed = _parse_when(text)
    if parsed is None or min_gap_minutes(parsed[0]) < MIN_INTERVAL_MINUTES:
        return None
    return parsed


def _parse_when(text: str) -> tuple[str, str] | None:
    """``parse_when`` without the interval floor. Private so the floor cannot
    be skipped by accident — ``too_frequent_error`` needs the unbounded answer
    to explain itself."""
    s = (text or "").strip()
    if not s:
        return None

    # Raw 5-field cron passthrough — accept only if every field is in range.
    if re.fullmatch(r"[\d\*/,\-]+(?:\s+[\d\*/,\-]+){4}", s):
        return (s, f"on schedule `{s}`") if _is_valid_cron(s) else None

    low = s.lower()

    if low == "every morning":
        return "0 8 * * *", "every day at 8:00 AM"
    if low == "every evening":
        return "0 20 * * *", "every day at 8:00 PM"

    m = re.fullmatch(r"every (\d+) minutes?", low)
    if m:
        n = int(m.group(1))
        return f"*/{n} * * * *", f"every {n} minutes"

    m = re.fullmatch(r"every (\d+) hours?", low)
    if m:
        n = int(m.group(1))
        return f"0 */{n} * * *", f"every {n} hours"

    if low in ("hourly", "every hour"):
        return "0 * * * *", "every hour"

    # "every 9pm" / "every 9:26pm" / "every 21:00" -> daily at that time.
    # Require am/pm or a colon so a bare "every 9" (ambiguous) is not matched.
    m = re.fullmatch(r"every (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", low)
    if m and (m.group(2) is not None or m.group(3) is not None):
        hour = _to_24h(int(m.group(1)), m.group(3))
        minute = int(m.group(2)) if m.group(2) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{minute} {hour} * * *", f"every day at {_fmt_time(hour, minute)}"

    # "at 9pm" / "9:30pm" -> daily at that time (am/pm required to avoid ambiguity).
    m = re.fullmatch(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", low)
    if m:
        hour = _to_24h(int(m.group(1)), m.group(3))
        minute = int(m.group(2)) if m.group(2) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{minute} {hour} * * *", f"every day at {_fmt_time(hour, minute)}"

    # "every day at 8pm" / "daily at 6:30am" / "every day at 20:30"
    m = re.fullmatch(r"(?:every day|daily) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", low)
    if m:
        hour = _to_24h(int(m.group(1)), m.group(3))
        minute = int(m.group(2)) if m.group(2) else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return f"{minute} {hour} * * *", f"every day at {_fmt_time(hour, minute)}"

    # "every monday at 9am"
    m = re.fullmatch(
        r"every (sunday|monday|tuesday|wednesday|thursday|friday|saturday) "
        r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        low,
    )
    if m:
        day = _DAY_NUM[m.group(1)]
        hour = _to_24h(int(m.group(2)), m.group(4))
        minute = int(m.group(3)) if m.group(3) else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return (
            f"{minute} {hour} * * {day}",
            f"every {_DAY_NAME[day]} at {_fmt_time(hour, minute)}",
        )

    # "every weekday at 9am" / "weekdays at 9am" -> Mon-Fri at that time.
    m = re.fullmatch(
        r"(?:every )?weekdays? at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", low)
    if m:
        hour = _to_24h(int(m.group(1)), m.group(3))
        minute = int(m.group(2)) if m.group(2) else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return (
            f"{minute} {hour} * * 1-5",
            f"every weekday at {_fmt_time(hour, minute)}",
        )
    if low in ("every weekday", "weekday", "weekdays", "every weekdays"):
        return "0 8 * * 1-5", "every weekday at 8:00 AM"

    if low in ("daily", "every day"):
        return "0 8 * * *", "every day at 8:00 AM"
    if low in ("weekly", "every week"):
        return "0 8 * * 1", "every Monday at 8:00 AM"

    return None
