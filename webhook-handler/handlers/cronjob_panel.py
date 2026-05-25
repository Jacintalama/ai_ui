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


# ── custom_id constants ──────────────────────────────────────────────
NEW = f"{_PREFIX}:new"
LIST = f"{_PREFIX}:list"
SELECT = f"{_PREFIX}:select"
DOW_SELECT = f"{_PREFIX}:dow"
CUSTOM_CRON_MODAL = f"{_PREFIX}:customcron"
DELCANCEL = f"{_PREFIX}:delcancel"


def encode_cron(cron_expr: str) -> str:
    """Pack a cron expression into a single custom_id token (spaces -> '_')."""
    return cron_expr.replace(" ", "_")


def decode_cron(token: str) -> str:
    return token.replace("_", " ")


def is_cron(custom_id: str) -> bool:
    return custom_id.split(":", 1)[0] == _PREFIX


def is_new(c: str) -> bool:
    return c == NEW


def is_list(c: str) -> bool:
    return c == LIST


def is_schedule_select(c: str) -> bool:
    return c == SELECT


def is_dow_select(c: str) -> bool:
    return c == DOW_SELECT


def is_freq_button(c: str) -> bool:
    return c.startswith(f"{_PREFIX}:freq:")


def freq_from_button(c: str) -> str:
    prefix = f"{_PREFIX}:freq:"
    if not c.startswith(prefix):
        raise ValueError(c)
    return c[len(prefix):]


def hour_select_id(freq: str, dow: str | None = None) -> str:
    return f"{_PREFIX}:hour:{freq}" + (f":{dow}" if dow else "")


def is_hour_select(c: str) -> bool:
    return c.startswith(f"{_PREFIX}:hour:")


def hour_context_from_select(c: str) -> tuple[str, str | None]:
    prefix = f"{_PREFIX}:hour:"
    if not c.startswith(prefix):
        raise ValueError(c)
    bits = c[len(prefix):].split(":")
    return bits[0], (bits[1] if len(bits) > 1 else None)


def create_modal_id(cron_expr: str) -> str:
    return f"{_PREFIX}:create:{encode_cron(cron_expr)}"


def is_create_modal(c: str) -> bool:
    return c.startswith(f"{_PREFIX}:create:")


def is_custom_cron_modal(c: str) -> bool:
    return c == CUSTOM_CRON_MODAL


def cron_from_create_modal(c: str) -> str:
    prefix = f"{_PREFIX}:create:"
    if not c.startswith(prefix):
        raise ValueError(c)
    return decode_cron(c[len(prefix):])


def action_id(verb: str, schedule_id: str) -> str:
    return f"{_PREFIX}:{verb}:{schedule_id}"


def is_action(c: str, verb: str) -> bool:
    return c.startswith(f"{_PREFIX}:{verb}:")


def id_from_action(c: str, verb: str) -> str:
    prefix = f"{_PREFIX}:{verb}:"
    if not c.startswith(prefix):
        raise ValueError(c)
    return c[len(prefix):]
