"""Pure builders for the Slack recruiting-outreach panel and modal.

Block Kit analog of handlers/recruiting_panel.py. No I/O. Imported by the
interaction handler (handlers/slack_interactions.py) and unit-tested in
tests/test_slack_recruiting.py.

The action_id / callback_id constants mirror the Discord panel for consistency,
using a distinct Slack-safe namespace ("aiuiout:…").
"""
from __future__ import annotations

from handlers.slack_app_builder_panel import _button
from handlers.recruiting_panel import parse_outreach_modal as _parse_outreach_modal

__all__ = [
    "OUT_FIND_ACTION_ID",
    "OUT_MODAL_CALLBACK",
    "build_recruiting_blocks",
    "build_outreach_view",
    "outreach_fields_from_view",
    "sample_state",
]

# Stable action_id / callback_id constants.
OUT_FIND_ACTION_ID = "aiuiout:find"
OUT_MODAL_CALLBACK = "aiuiout:modal"

# Stable block_id / action_id pairs for the modal inputs.
_ROLE_BLOCK_ID = "out_role"
_ROLE_INPUT_ID = "out_role_input"
_LOCATION_BLOCK_ID = "out_location"
_LOCATION_INPUT_ID = "out_location_input"
_JOBDESC_BLOCK_ID = "out_jobdesc"
_JOBDESC_INPUT_ID = "out_jobdesc_input"
_COUNT_BLOCK_ID = "out_count"
_COUNT_INPUT_ID = "out_count_input"

_TITLE_MAX = 24  # Slack modal title hard limit


def build_recruiting_blocks() -> list[dict]:
    """Channel entry panel: a header section + an actions block with a single
    primary 'Find Engineers' button."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*\U0001f3af Recruiting Outreach*\n"
                    "Find software engineers and email them a job in one click. "
                    "Hit *\U0001f50d Find Engineers*, describe the role, and I'll "
                    "search GitHub, email those I can reach, and save everyone to "
                    "your shared sheet."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                _button("\U0001f50d Find Engineers", OUT_FIND_ACTION_ID, primary=True),
            ],
        },
    ]


def build_outreach_view(channel_id: str) -> dict:
    """Slack modal view for recruiting outreach. callback_id == OUT_MODAL_CALLBACK;
    the originating channel is stashed in private_metadata so the submit handler
    knows where to post results (modal submits don't carry the channel).

    Four input blocks: role (required), location (optional), jobdesc (multiline,
    required), count (optional, defaults to 10)."""
    return {
        "type": "modal",
        "callback_id": OUT_MODAL_CALLBACK,
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": "Find Engineers"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Search"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": _ROLE_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Skill / language"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": _ROLE_INPUT_ID,
                    "multiline": False,
                    "max_length": 100,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Python backend",
                    },
                },
            },
            {
                "type": "input",
                "block_id": _LOCATION_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Location (optional)"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": _LOCATION_INPUT_ID,
                    "multiline": False,
                    "max_length": 100,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Berlin",
                    },
                },
            },
            {
                "type": "input",
                "block_id": _JOBDESC_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Job description"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": _JOBDESC_INPUT_ID,
                    "multiline": True,
                    "max_length": 4000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "We're hiring a senior backend engineer to ...",
                    },
                },
            },
            {
                "type": "input",
                "block_id": _COUNT_BLOCK_ID,
                "label": {"type": "plain_text", "text": "How many to email (max 25)"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": _COUNT_INPUT_ID,
                    "multiline": False,
                    "max_length": 3,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "10",
                    },
                },
            },
        ],
    }


def outreach_fields_from_view(view: dict) -> tuple[str, str, str, int]:
    """Extract (role, location, jobdesc, count) from a view_submission payload's
    view dict. Reads view["state"]["values"] and delegates count clamping to
    recruiting_panel.parse_outreach_modal so the logic stays DRY."""
    values = (view or {}).get("state", {}).get("values", {})

    def _val(block_id: str, input_id: str) -> str:
        return (
            ((values.get(block_id) or {}).get(input_id) or {}).get("value") or ""
        ).strip()

    flat = {
        "role": _val(_ROLE_BLOCK_ID, _ROLE_INPUT_ID),
        "location": _val(_LOCATION_BLOCK_ID, _LOCATION_INPUT_ID),
        "jobdesc": _val(_JOBDESC_BLOCK_ID, _JOBDESC_INPUT_ID),
        "count": _val(_COUNT_BLOCK_ID, _COUNT_INPUT_ID),
    }
    return _parse_outreach_modal(flat)


def sample_state(role: str, location: str, jobdesc: str, count: str) -> dict:
    """Return a ``state.values`` dict shaped exactly as Slack sends it.

    Used in tests so that outreach_fields_from_view(view) and the test agree on
    the structure without duplicating the block_id / action_id constants."""
    def _entry(value: str) -> dict:
        return {"type": "plain_text_input", "value": value}

    return {
        _ROLE_BLOCK_ID: {_ROLE_INPUT_ID: _entry(role)},
        _LOCATION_BLOCK_ID: {_LOCATION_INPUT_ID: _entry(location)},
        _JOBDESC_BLOCK_ID: {_JOBDESC_INPUT_ID: _entry(jobdesc)},
        _COUNT_BLOCK_ID: {_COUNT_INPUT_ID: _entry(count)},
    }
