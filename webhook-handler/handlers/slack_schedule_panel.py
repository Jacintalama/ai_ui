"""Pure builders for the Slack cron-scheduler panel, dashboard, cards, and
modals. Slack mirror of the Discord schedule builders in app_builder_panel.py.

Block Kit shapes only (no I/O). action_ids / callback_ids are imported from
app_builder_panel so the routing constants stay DRY across Discord + Slack.

Slack note: Slack's _button has no danger/secondary style — only an optional
`primary=True`. "Primary" Discord actions map to primary=True; everything else
is a plain button.
"""
import json

from handlers.slack_app_builder_panel import _button
from handlers.schedule_format import cron_to_human
from handlers.app_builder_panel import (
    SCHED_OPEN_ID,
    SCHED_NEW_ID,
    SCHED_MODAL_ID,
    SCHED_EDITMODAL_PREFIX,
    SCHED_RUN_PREFIX,
    SCHED_PAUSE_PREFIX,
    SCHED_RESUME_PREFIX,
    SCHED_DEL_PREFIX,
    SCHED_EDIT_PREFIX,
    CONNECT_RESUME_PREFIX,
)

# Stable block_id / action_id pairs for the modal inputs.
SCHED_WHAT_BLOCK_ID = "sched_what"
SCHED_WHAT_INPUT_ID = "sched_what_input"
SCHED_WHEN_BLOCK_ID = "sched_when"
SCHED_WHEN_INPUT_ID = "sched_when_input"

# Native date/time picker block/action ids for the create modal.
SCHED_REPEAT_BLOCK_ID = "sched_repeat"
SCHED_REPEAT_ACTION_ID = "sched_repeat_input"
SCHED_TIME_BLOCK_ID = "sched_time"
SCHED_TIME_ACTION_ID = "sched_time_input"
SCHED_WEEKDAY_BLOCK_ID = "sched_weekday"
SCHED_WEEKDAY_ACTION_ID = "sched_weekday_input"
SCHED_DATE_BLOCK_ID = "sched_date"
SCHED_DATE_ACTION_ID = "sched_date_input"

# value strings map 1:1 to schedule_picker picks (kind/freq), except one_time.
REPEAT_OPTIONS = [
    ("One time", "one_time"), ("Every day", "daily"), ("Weekdays", "weekdays"),
    ("Every week", "weekly"), ("Every hour", "hourly"), ("Every 30 min", "every30"),
]
_SLACK_WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]

_TITLE_MAX = 24  # Slack modal title limit


def _opt(text: str, value: str) -> dict:
    return {"text": {"type": "plain_text", "text": text}, "value": value}


_EDIT_VALUE_PROMPT_MAX = 1500  # leave headroom under Slack's 2000-char value cap


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
    """Muted, smaller helper line (Slack renders context blocks in gray)."""
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _divider() -> dict:
    return {"type": "divider"}


def _new_schedule_actions() -> dict:
    """The '➕ New schedule' actions block, pinned at the bottom of the list."""
    return {
        "type": "actions",
        "elements": [_button("➕ New schedule", SCHED_NEW_ID, primary=True)],
    }


def _build_edit_button(sched: dict, sid: str) -> dict:
    """Primary 'Edit' button whose `value` carries the prefill (id/prompt/cron)
    as JSON, so the edit modal can be opened synchronously at click time with no
    network fetch. Prompt is truncated to stay under Slack's 2000-char value cap.
    The action_id stays exactly SCHED_EDIT_PREFIX+id so routing is unchanged."""
    value = json.dumps(
        {
            "id": sid,
            "prompt": (sched.get("prompt") or "")[:_EDIT_VALUE_PROMPT_MAX],
            "cron": sched.get("cron_expr", ""),
        }
    )
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "✏️ Edit"},
        "style": "primary",
        "action_id": f"{SCHED_EDIT_PREFIX}{sid}",
        "value": value,
    }


def build_schedules_panel() -> list[dict]:
    """Channel entry panel: a header section + an actions block with a single
    primary 'Open my schedules' button."""
    return [
        _section("*📅 Scheduled tasks*\nSet up tasks that run on a schedule."),
        {
            "type": "actions",
            "elements": [
                _button("⏰ Open my schedules", SCHED_OPEN_ID, primary=True),
            ],
        },
    ]


def build_schedules_dashboard(schedules: list[dict]) -> list[dict]:
    """Posted in the user's private view: a big header + a live active/paused
    count, then one card per schedule separated by divider rails, with the
    '➕ New schedule' button pinned at the bottom. Empty list → a friendly
    'no schedules' section."""
    header = {
        "type": "header",
        "text": {"type": "plain_text", "text": "📅 Your Schedules", "emoji": True},
    }
    if not schedules:
        return [
            header,
            _section("_You have no schedules yet. Create one below._"),
            _divider(),
            _new_schedule_actions(),
        ]

    active = sum(1 for s in schedules if s.get("enabled", True))
    paused = len(schedules) - active
    count = f"{active} active"
    if paused:
        count += f" · {paused} paused"

    blocks: list[dict] = [header, _context(count), _divider()]
    for sched in schedules:
        blocks.extend(build_schedule_card(sched))
        blocks.append(_divider())
    blocks.append(_new_schedule_actions())
    return blocks


def build_schedule_card(sched: dict) -> list[dict]:
    """A section describing one schedule + an actions block with state-aware
    Run / Pause-or-Resume / Edit / Delete buttons (≤5 elements)."""
    sid = str(sched.get("id", ""))
    prompt = (sched.get("prompt") or "").strip() or "(no description)"
    cron_raw = (sched.get("cron_expr") or "").strip()
    when = cron_to_human(cron_raw) if cron_raw else "—"
    enabled = sched.get("enabled", True)
    badge = "🟢 Active" if enabled else "⚪ Paused"

    elements = [_button("▶️ Run now", f"{SCHED_RUN_PREFIX}{sid}")]
    if enabled:
        elements.append(_button("⏸ Pause", f"{SCHED_PAUSE_PREFIX}{sid}"))
    else:
        elements.append(_button("▶️ Resume", f"{SCHED_RESUME_PREFIX}{sid}"))
    elements.append(_build_edit_button(sched, sid))
    elements.append(_button("🗑 Delete", f"{SCHED_DEL_PREFIX}{sid}"))

    return [
        _section(f"*{prompt}*\n🕗 {when}   {badge}"),
        {"type": "actions", "elements": elements},
    ]


def build_schedule_modal() -> dict:
    """Create-schedule modal view (callback_id == SCHED_MODAL_ID): a 'what' input
    plus native Repeat / time / weekday / date pickers. The picker values are
    resolved by slack_picks_from_view -> schedule_picker.picks_to_cron. All picker
    blocks are present; the converter uses only the ones relevant to the chosen
    Repeat (weekday for weekly, date for one-time)."""
    repeat_opts = [_opt(label, val) for label, val in REPEAT_OPTIONS]
    weekday_opts = [_opt(d.capitalize(), d) for d in _SLACK_WEEKDAYS]
    return {
        "type": "modal",
        "callback_id": SCHED_MODAL_ID,
        "title": {"type": "plain_text", "text": "New schedule"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Create"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": SCHED_WHAT_BLOCK_ID,
                "label": {"type": "plain_text", "text": "What should it do?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": SCHED_WHAT_INPUT_ID,
                    "multiline": True,
                    "max_length": 2000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. summarize my unread emails and list the top 3",
                    },
                },
            },
            {
                "type": "input",
                "block_id": SCHED_REPEAT_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Repeat"},
                "element": {
                    "type": "static_select",
                    "action_id": SCHED_REPEAT_ACTION_ID,
                    "initial_option": repeat_opts[1],  # Every day
                    "options": repeat_opts,
                },
            },
            {
                "type": "input",
                "block_id": SCHED_TIME_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Time (Manila)"},
                "element": {
                    "type": "timepicker",
                    "action_id": SCHED_TIME_ACTION_ID,
                    "initial_time": "09:00",
                },
            },
            {
                "type": "input",
                "block_id": SCHED_WEEKDAY_BLOCK_ID,
                "optional": True,
                "label": {"type": "plain_text", "text": "Day of week (for weekly)"},
                "element": {
                    "type": "static_select",
                    "action_id": SCHED_WEEKDAY_ACTION_ID,
                    "options": weekday_opts,
                },
            },
            {
                "type": "input",
                "block_id": SCHED_DATE_BLOCK_ID,
                "optional": True,
                "label": {"type": "plain_text", "text": "Date (for one-time)"},
                "element": {
                    "type": "datepicker",
                    "action_id": SCHED_DATE_ACTION_ID,
                },
            },
        ],
    }


def _selected_value(state: dict, block: str, action: str):
    el = (state.get(block, {}) or {}).get(action, {}) or {}
    opt = el.get("selected_option")
    return opt.get("value") if opt else None


def slack_picks_from_view(view: dict) -> dict:
    """Map the create modal's Block Kit state into a schedule_picker picks dict."""
    state = (view.get("state", {}) or {}).get("values", {}) or {}
    repeat = _selected_value(state, SCHED_REPEAT_BLOCK_ID, SCHED_REPEAT_ACTION_ID) or "daily"
    weekday = _selected_value(state, SCHED_WEEKDAY_BLOCK_ID, SCHED_WEEKDAY_ACTION_ID)
    time_v = ((state.get(SCHED_TIME_BLOCK_ID, {}) or {}).get(
        SCHED_TIME_ACTION_ID, {}) or {}).get("selected_time")
    date_v = ((state.get(SCHED_DATE_BLOCK_ID, {}) or {}).get(
        SCHED_DATE_ACTION_ID, {}) or {}).get("selected_date")
    picks: dict = {}
    if repeat == "one_time":
        picks["kind"] = "once"
        if date_v:
            picks["date"] = date_v
    else:
        picks["kind"] = "rep"
        picks["freq"] = repeat
        if weekday:
            picks["weekday"] = weekday
    if time_v:
        picks["hour"] = str(int(time_v.split(":")[0]))
    return picks


def sample_view_state(repeat: str, time: str = "09:00", weekday=None, date=None) -> dict:
    """Test helper: a view.state.values dict shaped like Slack sends it."""
    values: dict = {
        SCHED_REPEAT_BLOCK_ID: {SCHED_REPEAT_ACTION_ID: {
            "selected_option": {"value": repeat}}},
        SCHED_TIME_BLOCK_ID: {SCHED_TIME_ACTION_ID: {"selected_time": time}},
    }
    if weekday:
        values[SCHED_WEEKDAY_BLOCK_ID] = {SCHED_WEEKDAY_ACTION_ID: {
            "selected_option": {"value": weekday}}}
    if date:
        values[SCHED_DATE_BLOCK_ID] = {SCHED_DATE_ACTION_ID: {"selected_date": date}}
    return values


def build_schedule_edit_modal(sched: dict) -> dict:
    """Edit-schedule modal view (callback_id == SCHED_EDITMODAL_PREFIX+id) with
    the 'what' input pre-filled from prompt and 'when' shown in plain English
    (e.g. 'every day at 2:00 PM') instead of the raw cron, matching Discord.
    parse_when round-trips the English back to cron on save."""
    sid = str(sched.get("id", ""))
    prompt = (sched.get("prompt") or "").strip()
    cron = (sched.get("cron_expr") or "").strip()
    when = cron_to_human(cron) if cron else ""
    return {
        "type": "modal",
        "callback_id": f"{SCHED_EDITMODAL_PREFIX}{sid}",
        "title": {"type": "plain_text", "text": "Edit schedule"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": SCHED_WHAT_BLOCK_ID,
                "label": {"type": "plain_text", "text": "What should it do?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": SCHED_WHAT_INPUT_ID,
                    "multiline": True,
                    "max_length": 2000,
                    "initial_value": prompt,
                },
            },
            {
                "type": "input",
                "block_id": SCHED_WHEN_BLOCK_ID,
                "label": {"type": "plain_text", "text": "When?"},
                "hint": {
                    "type": "plain_text",
                    "text": "A cron expression or plain English both work.",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": SCHED_WHEN_INPUT_ID,
                    "multiline": False,
                    "max_length": 100,
                    "initial_value": when,
                },
            },
        ],
    }


def build_connect_blocks(
    token: str, links: list[tuple[str, str]], header: str
) -> list[dict]:
    """Connect-when-needed card: a header section + one link button per connector
    to authorize, plus a primary '✅ I've connected — create it' button carrying
    the parked-schedule token. Mirrors the Discord connect card."""
    elements: list[dict] = []
    for label, url in links:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": f"🔗 Connect {label}"},
            "url": url,
            "action_id": f"aiuisched:connectlink:{label.lower()}",
        })
    elements.append(_button(
        "✅ I've connected — create it",
        f"{CONNECT_RESUME_PREFIX}{token}", primary=True,
    ))
    return [_section(header), {"type": "actions", "elements": elements}]


def build_retry_blocks(schedule_id: str) -> list[dict]:
    """A single-button actions block: 'Retry' re-runs the schedule (Slack-native;
    not Discord's build_retry_components)."""
    return [
        {
            "type": "actions",
            "elements": [
                _button("🔁 Retry", f"{SCHED_RUN_PREFIX}{schedule_id}"),
            ],
        }
    ]
