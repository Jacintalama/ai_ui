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
)

# Stable block_id / action_id pairs for the modal inputs.
SCHED_WHAT_BLOCK_ID = "sched_what"
SCHED_WHAT_INPUT_ID = "sched_what_input"
SCHED_WHEN_BLOCK_ID = "sched_when"
SCHED_WHEN_INPUT_ID = "sched_when_input"

_TITLE_MAX = 24  # Slack modal title limit


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
    """Create-schedule modal view (callback_id == SCHED_MODAL_ID): a multiline
    'what' input + a single-line 'when' input."""
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
                    "placeholder": {
                        "type": "plain_text",
                        "text": "0 9 * * *  /  every morning  /  every Monday 9am",
                    },
                },
            },
        ],
    }


def build_schedule_edit_modal(sched: dict) -> dict:
    """Edit-schedule modal view (callback_id == SCHED_EDITMODAL_PREFIX+id) with
    the 'what' input pre-filled from prompt and 'when' from the raw cron_expr."""
    sid = str(sched.get("id", ""))
    prompt = (sched.get("prompt") or "").strip()
    cron = (sched.get("cron_expr") or "").strip()
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
                    "initial_value": cron,
                },
            },
        ],
    }


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
