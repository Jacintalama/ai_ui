"""Pure date/time picker logic for schedules: UI picks -> (cron, run_once, label).
Reuses schedule_parse's cron grammar + label helpers. No I/O."""
from __future__ import annotations

from datetime import datetime, timedelta

from handlers.schedule_parse import _DAY_NUM, _DAY_NAME, _fmt_time
from handlers.app_builder_panel import (
    ACTION_ROW, BUTTON, SELECT_MENU, TEXT_INPUT,
    STYLE_PRIMARY, STYLE_SECONDARY, STYLE_SUCCESS, TEXT_PARAGRAPH, _button,
)

# --- custom_id namespace (Discord) ---
PICK_PREFIX = "aiuisched:pick:"          # aiuisched:pick:<field>:<token>
TASK_MODAL_PREFIX = "aiuisched:pick:taskmodal:"  # the final "set the task" modal
TASK_INPUT_ID = "what"

# Field names used in pick custom_ids. Selects carry their choice as the
# interaction VALUE; the kind/quick-date BUTTONS carry it in the field name.
FREQ_OPTIONS = [
    ("Every day", "daily"), ("Weekdays", "weekdays"), ("Every week", "weekly"),
    ("Every hour", "hourly"), ("Every 30 min", "every30"),
]
_WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
_MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DOW_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # datetime.weekday() order


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


# ---------------------------------------------------------------------------
# Discord picker builders (cards + the final "set the task" modal).
# Selects live in their own action row; a message holds <=5 rows; selects cap
# at 25 options. A select's chosen value arrives as the interaction VALUE; the
# kind / quick-date BUTTONS encode their choice in the field name.
# ---------------------------------------------------------------------------

def _select(field: str, token: str, placeholder: str,
            options: list[dict], selected: str | None) -> dict:
    opts = []
    for o in options:
        opt = {"label": o["label"][:100], "value": o["value"][:100]}
        if selected is not None and o["value"] == selected:
            opt["default"] = True
        opts.append(opt)
    return {"type": ACTION_ROW, "components": [{
        "type": SELECT_MENU, "custom_id": pick_cid(field, token),
        "placeholder": placeholder[:150], "min_values": 1, "max_values": 1,
        "options": opts,
    }]}


def _hour_options() -> list[dict]:
    return [{"label": _fmt_time(h, 0), "value": str(h)} for h in range(24)]


def _weekday_options() -> list[dict]:
    return [{"label": name.capitalize(), "value": name} for name in _WEEKDAYS]


def _freq_options() -> list[dict]:
    return [{"label": label, "value": val} for label, val in FREQ_OPTIONS]


def next_14_day_options(now: datetime) -> list[dict]:
    """14 dated options starting today; value=YYYY-MM-DD, label e.g. 'Mon, Jun 15'."""
    out = []
    for i in range(14):
        d = now + timedelta(days=i)
        label = f"{_DOW_ABBR[d.weekday()]}, {_MON_ABBR[d.month - 1]} {d.day}"
        if i == 0:
            label = f"Today ({label})"
        out.append({"label": label, "value": d.strftime("%Y-%m-%d")})
    return out


def _footer_row(token: str, ready: bool) -> dict:
    buttons = []
    if ready:
        buttons.append(_button("✅ Set the task", pick_cid("settask", token), STYLE_SUCCESS))
    buttons.append(_button("⌨️ Type it instead", pick_cid("typeit", token), STYLE_SECONDARY))
    return {"type": ACTION_ROW, "components": buttons}


def build_kind_card(token: str) -> dict:
    """First step: choose repeating vs one-time."""
    return {"content": "⏰ **When should this run?**", "components": [
        {"type": ACTION_ROW, "components": [
            _button("🔁 Repeating", pick_cid("kindrep", token), STYLE_PRIMARY),
            _button("1️⃣ Just once", pick_cid("kindonce", token), STYLE_SECONDARY),
        ]},
    ]}


def _repeating_ready(picks: dict) -> bool:
    freq = picks.get("freq")
    if not freq:
        return False
    if freq in ("hourly", "every30"):
        return True
    if not picks.get("hour"):
        return False
    if freq == "weekly" and not picks.get("weekday"):
        return False
    return True


def build_repeating_card(token: str, picks: dict) -> dict:
    """Repeating picks: frequency (+ time, + weekday for weekly)."""
    freq = picks.get("freq")
    rows = [_select("freq", token, "How often?", _freq_options(), freq)]
    if freq in ("daily", "weekdays", "weekly"):
        rows.append(_select("hour", token, "What time? (Manila)", _hour_options(),
                            picks.get("hour")))
    if freq == "weekly":
        rows.append(_select("weekday", token, "Which day?", _weekday_options(),
                            picks.get("weekday")))
    rows.append(_footer_row(token, _repeating_ready(picks)))
    return {"content": "🔁 **Repeating schedule**", "components": rows}


def _onetime_ready(picks: dict) -> bool:
    return bool(picks.get("date") and picks.get("hour"))


def build_onetime_card(token: str, picks: dict, now: datetime) -> dict:
    """One-time picks: quick-pick date buttons + a 14-day dropdown + time."""
    rows = [
        {"type": ACTION_ROW, "components": [
            _button("Today", pick_cid("qtoday", token), STYLE_SECONDARY),
            _button("Tomorrow", pick_cid("qtomorrow", token), STYLE_SECONDARY),
            _button("Next Monday", pick_cid("qnextmon", token), STYLE_SECONDARY),
        ]},
        _select("date", token, "…or pick a date", next_14_day_options(now),
                picks.get("date")),
        _select("hour", token, "What time? (Manila)", _hour_options(), picks.get("hour")),
        _footer_row(token, _onetime_ready(picks)),
    ]
    return {"content": "1️⃣ **One-time schedule**", "components": rows}


def build_task_modal(token: str) -> dict:
    """Type-9 MODAL data: a single 'What should it do?' paragraph field. The
    custom_id carries the token so the submit handler can resolve the picks."""
    return {
        "title": "Set the task"[:45],
        "custom_id": f"{TASK_MODAL_PREFIX}{token}",
        "components": [{"type": ACTION_ROW, "components": [{
            "type": TEXT_INPUT, "custom_id": TASK_INPUT_ID,
            "label": "What should it do?", "style": TEXT_PARAGRAPH,
            "required": True, "max_length": 2000,
            "placeholder": "e.g. summarize my unread emails and list the top 3",
        }]}],
    }


def quick_date_iso(field: str, now: datetime) -> str | None:
    """Resolve a quick-pick date button field to a YYYY-MM-DD string."""
    if field == "qtoday":
        return now.strftime("%Y-%m-%d")
    if field == "qtomorrow":
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if field == "qnextmon":
        # next Monday (datetime.weekday(): Monday=0); always strictly in the future
        ahead = (7 - now.weekday()) % 7 or 7
        return (now + timedelta(days=ahead)).strftime("%Y-%m-%d")
    return None
