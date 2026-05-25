"""Pure builders + parsers for the Discord cron-job panel.

No I/O. Every function maps inputs to Discord component dicts or parses a
custom_id. Mirrors app_builder_panel.py. Tested in tests/test_cronjob_panel.py.
"""
from __future__ import annotations

_PREFIX = "cron"

_DOW_DESC = {
    "0": "Sundays", "1": "Mondays", "2": "Tuesdays", "3": "Wednesdays",
    "4": "Thursdays", "5": "Fridays", "6": "Saturdays",
}


def cron_from_choice(freq: str, hour: int | None = None, dow: str | None = None) -> str:
    """Build a 5-field cron expression from a friendly choice."""
    if freq == "hourly":
        return "0 * * * *"
    if hour is None:
        raise ValueError(f"hour required for freq={freq!r}")
    if freq == "daily":
        return f"0 {hour} * * *"
    if freq == "weekdays":
        return f"0 {hour} * * 1-5"
    if freq == "weekly":
        if dow is None:
            raise ValueError("dow required for weekly")
        return f"0 {hour} * * {dow}"
    raise ValueError(f"unknown freq={freq!r}")


def describe_cron(cron_expr: str) -> str:
    """Humanize a cron expression for confirmations / the schedule menu.

    Falls back to echoing the raw string for anything it can't humanize.
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    minute, hour, dom, mon, dow = parts
    if minute == "0" and hour == "*" and dom == "*" and mon == "*" and dow == "*":
        return "every hour"
    if not (minute.isdigit() and hour.isdigit()):
        return cron_expr
    t = f"{int(hour):02d}:{int(minute):02d}"
    if dom == "*" and mon == "*":
        if dow == "*":
            return f"daily at {t}"
        if dow == "1-5":
            return f"weekdays at {t}"
        if dow in _DOW_DESC:
            return f"{_DOW_DESC[dow]} at {t}"
    return cron_expr
