"""Confirm/suggest cards for the intent router. Pure builders, tested like
onboarding.py. Reuses the existing Discord/Slack button helpers so styling
stays consistent."""
from __future__ import annotations

from handlers.app_builder_panel import (
    ACTION_ROW, STYLE_SUCCESS, STYLE_PRIMARY, _button,
)
from handlers.slack_app_builder_panel import _button as _slack_button

INTENT_CONFIRM_PREFIX = "aiuiintent:confirm:"
INTENT_CANCEL_PREFIX = "aiuiintent:cancel:"

_VERB = {
    "build_app": "build a website",
    "schedule_task": "set up a scheduled task",
    "make_video": "make a video",
    "find_jobs": "find jobs for you",
    "find_engineers": "find engineers to hire",
    "summarize_email": "summarize your email",
    "web_research": "research that for you",
    "daily_briefing": "set up a daily morning briefing",
}


def confirm_line(intent: str, detail: str) -> str:
    return f"Sounds like you want me to {_VERB.get(intent, 'help with that')}. Want me to start?"


def suggest_line(intent: str) -> str:
    return (
        f"Sounds like you want me to {_VERB.get(intent, 'help with that')}. "
        "Tap a button below to start, or just ask me anything."
    )


def confirm_components_discord(token: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Yes, do it", INTENT_CONFIRM_PREFIX + token, STYLE_SUCCESS),
        _button("Just answer", INTENT_CANCEL_PREFIX + token, STYLE_PRIMARY),
    ]}]


def confirm_blocks_slack(token: str, line: str) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": line}},
        {"type": "actions", "elements": [
            _slack_button("Yes, do it", INTENT_CONFIRM_PREFIX + token, primary=True),
            _slack_button("Just answer", INTENT_CANCEL_PREFIX + token),
        ]},
    ]
