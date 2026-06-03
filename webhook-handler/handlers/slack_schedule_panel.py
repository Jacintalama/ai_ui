"""Pure builders for the Slack cron-scheduler panel, dashboard, cards, and
modals. Slack mirror of the Discord schedule builders in app_builder_panel.py.

Block Kit shapes only (no I/O). action_ids / callback_ids are imported from
app_builder_panel so the routing constants stay DRY across Discord + Slack.

Slack note: Slack's _button has no danger/secondary style — only an optional
`primary=True`. "Primary" Discord actions map to primary=True; everything else
is a plain button.
"""
from handlers.slack_app_builder_panel import _button
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


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


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
    """Posted in the user's private view: a 'New schedule' button + one card per
    schedule. Empty list → a 'no schedules' section."""
    blocks: list[dict] = [
        _section("*📅 Your schedules*"),
        {
            "type": "actions",
            "elements": [_button("➕ New schedule", SCHED_NEW_ID, primary=True)],
        },
    ]
    if not schedules:
        blocks.append(_section("You have no schedules yet."))
        return blocks
    for sched in schedules:
        blocks.extend(build_schedule_card(sched))
    return blocks


def build_schedule_card(sched: dict) -> list[dict]:
    """A section describing one schedule + an actions block with state-aware
    Run / Pause-or-Resume / Edit / Delete buttons (≤5 elements)."""
    sid = str(sched.get("id", ""))
    prompt = (sched.get("prompt") or "").strip() or "(no description)"
    cron = (sched.get("cron_expr") or "").strip() or "—"
    enabled = sched.get("enabled", True)
    state = "🟢 enabled" if enabled else "⚪ paused"

    elements = [_button("▶️ Run now", f"{SCHED_RUN_PREFIX}{sid}")]
    if enabled:
        elements.append(_button("⏸ Pause", f"{SCHED_PAUSE_PREFIX}{sid}"))
    else:
        elements.append(_button("▶️ Resume", f"{SCHED_RESUME_PREFIX}{sid}"))
    elements.append(_button("✏️ Edit", f"{SCHED_EDIT_PREFIX}{sid}", primary=True))
    elements.append(_button("🗑 Delete", f"{SCHED_DEL_PREFIX}{sid}"))

    return [
        _section(f"*{prompt}*\n`{cron}` · {state}"),
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
