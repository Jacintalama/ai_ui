"""Pure builders for the #recruiting channel panel + outreach modal.

No I/O. Mirrors handlers/app_builder_panel.py. Imported by the Discord
interaction handler and unit-tested in tests/test_recruiting_panel.py.
"""
from __future__ import annotations

from handlers.app_builder_panel import (
    ACTION_ROW, BUTTON, TEXT_INPUT, STYLE_SUCCESS, STYLE_PRIMARY,
    TEXT_SHORT, TEXT_PARAGRAPH, ROBOTIC_CYAN, LINK_START_ID, _button,
)

__all__ = [
    "OUT_FIND_ID", "OUT_MODAL_ID", "OUT_ROLE_INPUT", "OUT_LOCATION_INPUT",
    "OUT_JOBDESC_INPUT", "OUT_COUNT_INPUT", "build_recruiting_panel",
    "build_recruiting_embed", "build_outreach_modal", "is_out_find",
    "is_out_modal", "parse_outreach_modal",
]

OUT_FIND_ID = "aiuiout:find"
OUT_MODAL_ID = "aiuiout:modal"
OUT_ROLE_INPUT = "role"
OUT_LOCATION_INPUT = "location"
OUT_JOBDESC_INPUT = "jobdesc"
OUT_COUNT_INPUT = "count"

_DEFAULT_COUNT = 10
_MAX_COUNT = 25

PANEL_CONTENT = (
    "\U0001f3af **Recruiting Outreach**\n"
    "Find software engineers and email them a job in one click. Hit "
    "**\U0001f50d Find Engineers**, describe the role, and I'll search GitHub, "
    "email those I can reach, and save everyone to your shared sheet."
)


def build_recruiting_panel() -> dict:
    """Pinned #recruiting panel: Find Engineers + the self-service Link button."""
    row = {"type": ACTION_ROW, "components": [
        _button("\U0001f50d Find Engineers", OUT_FIND_ID, STYLE_SUCCESS),
        _button("\U0001f517 Link my account", LINK_START_ID, STYLE_PRIMARY),
    ]}
    return {"content": PANEL_CONTENT, "components": [row]}


def build_recruiting_embed() -> dict:
    """Terminal/console-styled embed for the #recruiting channel panel."""
    return {
        "title": "\U0001f3af AIUI · RECRUITING",
        "color": ROBOTIC_CYAN,
        "description": (
            "```\n"
            "> describe the role + paste a job description\n"
            "> source: github + web search\n"
            "> emails sent to those with a public address\n"
            "> everyone saved to your google sheet\n"
            "```"
        ),
        "footer": {"text": "AIUI · outreach unit"},
    }


def build_outreach_modal() -> dict:
    """Type-9 MODAL data: role, location, job description, count."""
    def _ti(cid, label, style, required, maxlen, placeholder):
        return {"type": ACTION_ROW, "components": [{
            "type": TEXT_INPUT, "custom_id": cid, "label": label, "style": style,
            "required": required, "max_length": maxlen, "placeholder": placeholder,
        }]}
    return {
        "title": "Find Engineers"[:45],
        "custom_id": OUT_MODAL_ID,
        "components": [
            _ti(OUT_ROLE_INPUT, "Skill / language", TEXT_SHORT, True, 100,
                "e.g. Python backend"),
            _ti(OUT_LOCATION_INPUT, "Location (optional)", TEXT_SHORT, False, 100,
                "e.g. Berlin"),
            _ti(OUT_JOBDESC_INPUT, "Job description", TEXT_PARAGRAPH, True, 4000,
                "We're hiring a senior backend engineer to ..."),
            _ti(OUT_COUNT_INPUT, "How many to email (max 25)", TEXT_SHORT, False, 3,
                "10"),
        ],
    }


def is_out_find(custom_id: str) -> bool:
    return custom_id == OUT_FIND_ID


def is_out_modal(custom_id: str) -> bool:
    return custom_id == OUT_MODAL_ID


def parse_outreach_modal(values: dict) -> tuple[str, str, str, int]:
    """Flattened {custom_id: value} -> (role, location, jobdesc, count).
    count defaults to 10 and is clamped to 1..25."""
    role = (values.get(OUT_ROLE_INPUT) or "").strip()
    location = (values.get(OUT_LOCATION_INPUT) or "").strip()
    jobdesc = (values.get(OUT_JOBDESC_INPUT) or "").strip()
    raw = (values.get(OUT_COUNT_INPUT) or "").strip()
    try:
        count = int(raw)
    except (TypeError, ValueError):
        count = _DEFAULT_COUNT
    count = max(1, min(_MAX_COUNT, count))
    return role, location, jobdesc, count
