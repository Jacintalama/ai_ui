"""#channels: the web Channels page as a pinned Discord panel.

Pure builders and custom_id predicates, mirroring cronjob_panel.py. The web
page lists every chat platform this account can link to IO (Telegram, a
terminal, and so on) with the link status of each; linking itself is a pairing
step that belongs on the page. So the panel offers the one thing a message can
do, show your status, and a link button for the rest. Rendering of the status
reply lives in CommandRouter._handle_channels, shared with `/aiui channels`.
"""

_PREFIX = "chan"

# custom_ids
MY = f"{_PREFIX}:my"


def is_chan(custom_id: str) -> bool:
    return custom_id.split(":", 1)[0] == _PREFIX


def is_my(custom_id: str) -> bool:
    return custom_id == MY


def channels_url(base_url: str) -> str:
    """The web page. `/channel` is the short URL the sidebar pane owns."""
    return f"{base_url.rstrip('/')}/channel"


def build_panel_payload(base_url: str) -> dict:
    return {
        "content": (
            "**Channels**\n"
            "Talk to IO from Telegram, a terminal and more.\n"
            "• **My channels** — which ones you have linked\n"
            "• **Link a channel** — opens the Channels page"
        ),
        "components": [
            {
                "type": 1,
                "components": [
                    {"type": 2, "style": 1, "label": "My channels", "custom_id": MY},
                    {"type": 2, "style": 5, "label": "Link a channel",
                     "url": channels_url(base_url)},
                ],
            }
        ],
    }
