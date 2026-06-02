"""Pure builders for the Slack App Builder channel panel and modal.

Block Kit analog of handlers/app_builder_panel.py. No I/O. Imported by the
interaction handler (handlers/slack_interactions.py) and the one-shot setup
script (scripts/setup_slack_app_builder_channel.py); unit tested in
tests/test_slack_panel.py.

The custom-id prefixes match the Discord panel for consistency, but Slack uses
them as `action_id` (buttons) and `callback_id` (modal views).
"""
from __future__ import annotations

# custom_id schemes (shared shape with the Discord panel)
TEMPLATE_PREFIX = "aiuibuild:tpl:"   # button action_id -> aiuibuild:tpl:<key>  ("" = Blank)
BUILD_PREFIX = "aiuibuild:build:"    # modal callback_id -> aiuibuild:build:<key>
DESCRIPTION_BLOCK_ID = "description_block"
DESCRIPTION_INPUT_ID = "description"

# Slack Block Kit limits
_MAX_PER_ACTIONS_BLOCK = 5
_MAX_BUTTONS = 25          # leave the rest to the slash command
_BUTTON_TEXT_MAX = 75
_TITLE_MAX = 24           # modal title plain_text hard limit

PANEL_TEXT = (
    ":rocket: *AIUI App Builder*\n"
    "Pick a template to start — a short form opens where you describe your app. "
    "Or hit *Blank* to build from scratch. I'll post the live link here when "
    "it's ready."
)


def _button(text: str, action_id: str, *, primary: bool = False) -> dict:
    btn = {
        "type": "button",
        "text": {"type": "plain_text", "text": (text or "?")[:_BUTTON_TEXT_MAX], "emoji": True},
        "action_id": action_id,
    }
    if primary:
        btn["style"] = "primary"
    return btn


def build_panel_blocks(templates: list[dict]) -> list[dict]:
    """Block Kit panel: a header section plus actions blocks (max 5 buttons
    each) — one button per template plus a trailing Blank button. Templates
    beyond the 24-button budget (room left for Blank) are dropped; the slash
    command still reaches them. Keyless rows are tolerated, not fatal."""
    buttons: list[dict] = []
    for t in templates[: _MAX_BUTTONS - 1]:
        key = t.get("key")
        if not key:
            continue  # tolerate a malformed row rather than crash
        emoji = (t.get("emoji") or "").strip()
        label = t.get("label", key)
        text = f"{emoji} {label}".strip()
        buttons.append(_button(text, f"{TEMPLATE_PREFIX}{key}", primary=(len(buttons) % 2 == 0)))
    buttons.append(_button("Blank", TEMPLATE_PREFIX))

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": PANEL_TEXT}}
    ]
    for start in range(0, len(buttons), _MAX_PER_ACTIONS_BLOCK):
        blocks.append(
            {"type": "actions", "elements": buttons[start : start + _MAX_PER_ACTIONS_BLOCK]}
        )
    return blocks


def build_modal_view(
    template_key: str | None,
    template_label: str | None = None,
    channel_id: str = "",
) -> dict:
    """A Slack modal `view`. callback_id carries the template key; the
    originating channel is stashed in private_metadata so the submit handler
    knows where to post the result (modal submits don't carry the channel)."""
    key = template_key or ""
    what = template_label or template_key or "app"
    return {
        "type": "modal",
        "callback_id": f"{BUILD_PREFIX}{key}",
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": f"Build: {what}"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Build"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": DESCRIPTION_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Describe your app"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": DESCRIPTION_INPUT_ID,
                    "multiline": True,
                    "max_length": 3000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. a portfolio site for Maya, a UX designer",
                    },
                },
            }
        ],
    }


def description_from_view(view: dict) -> str:
    """Pull the typed description out of a view_submission payload's view.
    view.state.values[DESCRIPTION_BLOCK_ID][DESCRIPTION_INPUT_ID].value."""
    values = (view or {}).get("state", {}).get("values", {})
    block = values.get(DESCRIPTION_BLOCK_ID, {})
    element = block.get(DESCRIPTION_INPUT_ID, {})
    return (element.get("value") or "").strip()


def is_panel_button(action_id: str) -> bool:
    return bool(action_id) and action_id.startswith(TEMPLATE_PREFIX)


def is_panel_modal(callback_id: str) -> bool:
    return bool(callback_id) and callback_id.startswith(BUILD_PREFIX)


def template_key_from_button(action_id: str) -> str | None:
    """Button action_id -> template key. Bare prefix (Blank) -> None."""
    if not is_panel_button(action_id):
        raise ValueError(f"not a panel button action_id: {action_id!r}")
    return action_id[len(TEMPLATE_PREFIX):] or None


def template_key_from_modal(callback_id: str) -> str | None:
    """Modal callback_id -> template key. Bare prefix -> None."""
    if not is_panel_modal(callback_id):
        raise ValueError(f"not a panel modal callback_id: {callback_id!r}")
    return callback_id[len(BUILD_PREFIX):] or None
