"""Human-readable rendering for schedules (the opposite direction of
schedule_parse): cron → plain English, status icons, and dropdown labels.
Pure, no I/O — unit tested in tests/test_schedule_format.py.
"""
from __future__ import annotations

import re

_DAY_NAME = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
             4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}


def _fmt_time(hour: int, minute: int) -> str:
    ampm = "AM" if hour < 12 else "PM"
    h12 = hour % 12 or 12
    return f"{h12}:{minute:02d} {ampm}"


def cron_to_human(cron: str) -> str:
    """Render common cron expressions as plain English; exotic ones fall back
    to the raw string (so we never show something misleading)."""
    parts = (cron or "").split()
    if len(parts) != 5:
        return cron or ""
    minute, hour, dom, month, dow = parts
    star_rest = (dom == "*" and month == "*" and dow == "*")

    if minute == "*" and hour == "*" and star_rest:
        return "every minute"
    m = re.fullmatch(r"\*/(\d+)", minute)
    if m and hour == "*" and star_rest:
        return f"every {m.group(1)} minutes"
    mh = re.fullmatch(r"\*/(\d+)", hour)
    if minute == "0" and mh and star_rest:
        return f"every {mh.group(1)} hours"
    if minute == "0" and hour == "*" and star_rest:
        return "every hour"
    if minute.isdigit() and hour.isdigit() and star_rest:
        return f"every day at {_fmt_time(int(hour), int(minute))}"
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow.isdigit():
        day = _DAY_NAME.get(int(dow), dow)
        return f"every {day} at {_fmt_time(int(hour), int(minute))}"
    return cron


def schedule_status_label(sched: dict) -> str:
    """Icon + words describing a schedule's state."""
    if not sched.get("enabled", True):
        return "⏸ paused"
    status = sched.get("last_run_status")
    if status == "running":
        return "⏳ running now"
    if status == "completed":
        return "✅ active · last run ok"
    if status == "failed":
        return "⚠️ active · last run failed"
    return "🟢 active"


def schedule_label(sched: dict) -> str:
    """Dropdown option label: '<when> — <task>' (single line, ≤100 chars)."""
    when = cron_to_human(sched.get("cron_expr", ""))
    prompt = (sched.get("prompt") or "").splitlines()[0] if (sched.get("prompt") or "") else ""
    label = f"{when} — {prompt}" if prompt else when
    return label[:100]
