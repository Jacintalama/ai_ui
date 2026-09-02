"""Slack #channels panel. Block Kit analog of channels_panel.py (Discord).

Pure builders. The one action, "My channels", is answered ephemerally by
CommandRouter._handle_channels; the link button opens the web page where
linking actually happens.
"""

MY_ACTION_ID = "chan_my"
LINK_ACTION_ID = "chan_link"  # url button; Slack still posts an action for it, which no-ops

_BUTTON_TEXT_MAX = 75


def channels_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/channel"


def _button(text: str, action_id: str, *, primary: bool = False) -> dict:
    btn = {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]},
        "action_id": action_id,
    }
    if primary:
        btn["style"] = "primary"
    return btn


def _link_button(text: str, action_id: str, url: str) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]},
        "action_id": action_id,
        "url": url,
    }


def build_channels_blocks(base_url: str) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Channels"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            "Talk to IO from Telegram, a terminal and more.\n"
            "• *My channels* — which ones you have linked\n"
            "• *Link a channel* — opens the Channels page")}},
        {"type": "actions", "elements": [
            _button("My channels", MY_ACTION_ID, primary=True),
            _link_button("Link a channel", LINK_ACTION_ID, channels_url(base_url)),
        ]},
    ]
