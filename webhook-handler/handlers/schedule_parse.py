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


def parse_when(text: str) -> tuple[str, str] | None:
    """Parse a human time phrase into ``(cron_expr, human_readable)``.

    Returns ``None`` when the phrase isn't a recognizable recurring time.
    """
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

    if low in ("daily", "every day"):
        return "0 8 * * *", "every day at 8:00 AM"
    if low in ("weekly", "every week"):
        return "0 8 * * 1", "every Monday at 8:00 AM"

    return None
