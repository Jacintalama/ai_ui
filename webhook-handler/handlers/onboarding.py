"""Pure builders for onboarding & linking UX: not-linked cards, the welcome
card, and the approval DM. No I/O — unit tested in tests/test_onboarding.py.

Copy here is the single source of truth for onboarding wording. It must never
contain a person's name or a raw OAuth scope instruction aimed at the end user.
"""
from __future__ import annotations

import re

from handlers.app_builder_panel import (
    ACTION_ROW,
    STYLE_SUCCESS,
    STYLE_PRIMARY,
    LINK_START_ID,
    PANEL_NEW_ID,
    SCHED_OPEN_ID,
    _button,
)

# --- Discord copy ---
WELCOME_TEXT_DISCORD = (
    "\U0001f44b Hi! I can **build you a website** or **run a task on a "
    "schedule** — no coding needed. Tap a button to start:"
)


def not_linked_text_discord() -> str:
    return (
        "\U0001f44b You're almost set up — tap **\U0001f517 Link my "
        "account** below to start building."
    )


def link_button_row() -> list[dict]:
    """One action row holding the existing self-service Link button."""
    return [{"type": ACTION_ROW, "components": [
        _button("\U0001f517 Link my account", LINK_START_ID, STYLE_PRIMARY),
    ]}]


def welcome_components_discord() -> list[dict]:
    """Welcome card buttons: Build an app + Schedule a task (existing entries)."""
    return [{"type": ACTION_ROW, "components": [
        _button("\U0001f680 Build an app", PANEL_NEW_ID, STYLE_SUCCESS),
        _button("⏰ Schedule a task", SCHED_OPEN_ID, STYLE_PRIMARY),
    ]}]


from handlers.slack_app_builder_panel import _button as _slack_button

# --- Slack copy ---
WELCOME_TEXT_SLACK = (
    ":wave: Hi! I can *build you a website* or *run a task on a schedule* "
    "— no coding needed. Tap a button to start:"
)


def not_linked_text_slack() -> str:
    return (
        "I can't see your email yet. Ask whoever set up this Slack workspace "
        "to turn on email access for the bot (the `users:read.email` "
        "permission), then try again."
    )


def _slack_welcome_action_elements() -> list[dict]:
    return [
        _slack_button("\U0001f680 Build an app", PANEL_NEW_ID, primary=True),
        _slack_button("⏰ Schedule a task", SCHED_OPEN_ID),
    ]


def welcome_blocks_slack() -> list[dict]:
    """Full welcome card: a section of copy + the two entry buttons."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": WELCOME_TEXT_SLACK}},
        {"type": "actions", "elements": _slack_welcome_action_elements()},
    ]


def buttons_footer_slack() -> dict:
    """Compact always-present footer (just the two buttons, no copy) appended
    under a normal AI answer so the entry points are always one tap away."""
    return {"type": "actions", "elements": _slack_welcome_action_elements()}


# --- shared heuristic ---
_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|help|start|get\s+started|getting\s+started|"
    r"how\s+do\s+i|how\s+to|what\s+can\s+you\s+do|what\s+do\s+you\s+do|"
    r"who\s+are\s+you|menu)\b",
    re.IGNORECASE,
)


def looks_like_getting_started(text: str) -> bool:
    """True for greetings/help/very-short messages (show the welcome card);
    False for substantive requests (answer normally + buttons footer)."""
    t = (text or "").strip()
    if not t:
        return True
    if len(t.split()) <= 2:
        return True
    return bool(_GREETING_RE.match(t))
