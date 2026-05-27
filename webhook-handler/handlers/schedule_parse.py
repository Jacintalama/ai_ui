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


# Named times-of-day → (hour, minute).
_WORD_TIMES = {
    "midnight": (0, 0), "morning": (8, 0), "noon": (12, 0),
    "afternoon": (15, 0), "evening": (20, 0), "night": (21, 0),
}


def _extract_time(low: str) -> tuple[int, int] | None:
    """Find a time anywhere in the phrase. Tries H:MM[(am|pm)], then H(am|pm),
    then named times (morning/noon/evening/night/midnight/afternoon)."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", low)
    if m:
        hour = _to_24h(int(m.group(1)), m.group(3))
        minute = int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", low)
    if m:
        hour = _to_24h(int(m.group(1)), m.group(2))
        if 0 <= hour <= 23:
            return hour, 0
    for word, hm in _WORD_TIMES.items():
        if re.search(rf"\b{word}\b", low):
            return hm
    return None


def _extract_dow(low: str) -> tuple[str, str] | None:
    """Find a day-of-week spec → (cron_dow_field, human_label). Handles single
    days (+plural), 'weekday(s)' → Mon-Fri, and 'weekend(s)' → Sat/Sun."""
    for name, num in _DAY_NUM.items():
        if re.search(rf"\b{name}s?\b", low):
            return str(num), _DAY_NAME[num]
    if re.search(r"\bweekdays?\b", low):
        return "1-5", "weekday"
    if re.search(r"\bweekends?\b", low):
        return "0,6", "weekend day"
    return None


def parse_when(text: str) -> tuple[str, str] | None:
    """Parse a human time phrase into ``(cron_expr, human_readable)``.

    Forgiving of casual phrasing — "every 8pm", "8pm", "9am everyday",
    "every monday 9am", "every weekday at 8am", "every 30 mins", "noon".
    Returns ``None`` when the phrase isn't a recognizable recurring time.
    """
    s = (text or "").strip()
    if not s:
        return None

    # Raw 5-field cron passthrough — accept only if every field is in range.
    if re.fullmatch(r"[\d\*/,\-]+(?:\s+[\d\*/,\-]+){4}", s):
        return (s, f"on schedule `{s}`") if _is_valid_cron(s) else None

    low = re.sub(r"\s+", " ", s.lower()).strip()

    # --- Intervals (checked first so a number isn't read as a clock time) ---
    m = re.search(r"every (\d+)\s*(?:minutes?|mins?|m)\b", low)
    if m and int(m.group(1)) >= 1:
        n = int(m.group(1))
        return f"*/{n} * * * *", f"every {n} minutes"
    m = re.search(r"every (\d+)\s*(?:hours?|hrs?|h)\b", low)
    if m and int(m.group(1)) >= 1:
        n = int(m.group(1))
        return f"0 */{n} * * *", f"every {n} hours"
    if re.search(r"\b(?:hourly|every hour)\b", low):
        return "0 * * * *", "every hour"
    if re.search(r"\bevery minute\b", low):
        return "* * * * *", "every minute"

    dow = _extract_dow(low)
    tm = _extract_time(low)

    if dow is not None:
        field, label = dow
        hour, minute = tm or (8, 0)
        return f"{minute} {hour} * * {field}", f"every {label} at {_fmt_time(hour, minute)}"

    if tm is not None or re.search(r"\b(?:daily|every ?day|each day)\b", low):
        hour, minute = tm or (8, 0)
        return f"{minute} {hour} * * *", f"every day at {_fmt_time(hour, minute)}"

    if re.search(r"\b(?:weekly|every week)\b", low):
        return "0 8 * * 1", "every Monday at 8:00 AM"

    return None
