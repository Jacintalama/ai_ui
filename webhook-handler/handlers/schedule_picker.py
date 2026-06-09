"""Pure date/time picker logic for schedules: UI picks -> (cron, run_once, label).
Reuses schedule_parse's cron grammar + label helpers. No I/O."""
from __future__ import annotations

from datetime import datetime

from handlers.schedule_parse import _DAY_NUM, _DAY_NAME, _fmt_time

# --- custom_id namespace (Discord) ---
PICK_PREFIX = "aiuisched:pick:"          # aiuisched:pick:<field>:<token>


class PastTimeError(ValueError):
    """Raised when a one-time schedule resolves to a moment already past."""


_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def pick_cid(field: str, token: str) -> str:
    return f"{PICK_PREFIX}{field}:{token}"


def parse_pick_cid(custom_id: str) -> tuple[str, str]:
    """`aiuisched:pick:<field>:<token>` -> (field, token)."""
    if not custom_id.startswith(PICK_PREFIX):
        raise ValueError(f"not a pick custom_id: {custom_id!r}")
    rest = custom_id[len(PICK_PREFIX):]
    field, _, token = rest.partition(":")
    return field, token


def picks_to_cron(picks: dict, *, now: datetime) -> tuple[str, bool, str]:
    """Convert accumulated UI picks into (cron_expr, run_once, human_label).
    Raises PastTimeError for a one-time datetime that is already past."""
    kind = picks.get("kind")
    if kind == "rep":
        freq = picks.get("freq")
        if freq == "hourly":
            return "0 * * * *", False, "every hour"
        if freq == "every30":
            return "*/30 * * * *", False, "every 30 minutes"
        hour = int(picks["hour"])
        label_time = _fmt_time(hour, 0)
        if freq == "daily":
            return f"0 {hour} * * *", False, f"every day at {label_time}"
        if freq == "weekdays":
            return f"0 {hour} * * 1-5", False, f"every weekday at {label_time}"
        if freq == "weekly":
            dow = _DAY_NUM[picks["weekday"].lower()]
            return (f"0 {hour} * * {dow}", False,
                    f"every {_DAY_NAME[dow]} at {label_time}")
        raise ValueError(f"unknown freq: {freq!r}")
    if kind == "once":
        hour = int(picks["hour"])
        y, m, d = (int(x) for x in picks["date"].split("-"))
        target = datetime(y, m, d, hour, 0)
        if target <= now:
            raise PastTimeError("one-time schedule is in the past")
        label = f"once on {_MONTHS[m - 1]} {d} at {_fmt_time(hour, 0)}"
        return f"0 {hour} {d} {m} *", True, label
    raise ValueError(f"unknown kind: {kind!r}")
