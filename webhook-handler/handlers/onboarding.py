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
from handlers.slack_app_builder_panel import _button as _slack_button

__all__ = [
    "WELCOME_TEXT_DISCORD",
    "WELCOME_TEXT_SLACK",
    "not_linked_text_discord",
    "link_button_row",
    "welcome_components_discord",
    "not_linked_text_slack",
    "welcome_blocks_slack",
    "buttons_footer_slack",
    "looks_like_getting_started",
    "approval_dm_discord",
]

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
    """True for greetings / help phrases / empty input (show the welcome card);
    False for substantive requests — including terse ones like "fix bug" — which
    are answered normally (the answer already carries a buttons footer)."""
    t = (text or "").strip()
    if not t:
        return True
    return bool(_GREETING_RE.match(t))


def approval_dm_discord(approved: bool) -> tuple[str, list[dict] | None]:
    """DM content sent to the requester when an admin decides their link request."""
    if approved:
        text = (
            "\U0001f389 You're in! Tap **\U0001f680 Build an app** to create "
            "your first one."
        )
        components = [{"type": ACTION_ROW, "components": [
            _button("\U0001f680 Build an app", PANEL_NEW_ID, STYLE_SUCCESS),
        ]}]
        return text, components
    text = (
        "Your access request wasn't approved this time. If you think that's a "
        "mistake, reach out to your team admin."
    )
    return text, None
