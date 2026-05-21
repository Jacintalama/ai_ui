"""Pure builders for the Discord App Builder channel panel and modal.

No I/O. Imported by the interaction handler (handlers/discord_commands.py) and
the one-shot setup script (scripts/setup_app_builder_channel.py); unit tested in
tests/test_app_builder_panel.py.
"""
from __future__ import annotations

# Discord component types
ACTION_ROW = 1
BUTTON = 2
TEXT_INPUT = 4

# Discord button styles
STYLE_PRIMARY = 1    # blurple ("blue")
STYLE_SECONDARY = 2  # grey
STYLE_SUCCESS = 3    # green
STYLE_LINK = 5       # link button (opens a URL; carries `url`, not custom_id)

# Text input styles
TEXT_PARAGRAPH = 2

# custom_id schemes
TEMPLATE_PREFIX = "aiuibuild:tpl:"   # button -> aiuibuild:tpl:<key>  ("" = Blank)
BUILD_PREFIX = "aiuibuild:build:"    # modal  -> aiuibuild:build:<key>
DESCRIPTION_INPUT_ID = "description"

_MAX_PER_ROW = 5
_MAX_ROWS = 5
_MAX_BUTTONS = _MAX_PER_ROW * _MAX_ROWS  # 25

PANEL_CONTENT = (
    "\U0001f680 **AIUI App Builder**\n"
    "Pick a template to start — a short form opens where you describe your app. "
    "Or hit **Blank** to build from scratch. I'll post the live link here when "
    "it's ready."
)


def _button(label: str, custom_id: str, style: int) -> dict:
    return {"type": BUTTON, "style": style, "label": label[:80], "custom_id": custom_id}


def build_panel_payload(templates: list[dict]) -> dict:
    """Pinned panel message: one green/blue button per template plus a grey Blank
    button, laid out 5 per row. Templates beyond the 24-button budget (room left
    for Blank) are dropped — the slash command still reaches them."""
    buttons: list[dict] = []
    for t in templates[: _MAX_BUTTONS - 1]:
        key = t.get("key")
        if not key:
            continue  # tolerate a malformed row rather than crash
        emoji = (t.get("emoji") or "").strip()
        label = t.get("label", key)
        text = f"{emoji} {label}".strip()
        style = STYLE_SUCCESS if len(buttons) % 2 == 0 else STYLE_PRIMARY
        buttons.append(_button(text, f"{TEMPLATE_PREFIX}{key}", style))
    buttons.append(_button("⬜ Blank", TEMPLATE_PREFIX, STYLE_SECONDARY))

    rows: list[dict] = []
    for start in range(0, len(buttons), _MAX_PER_ROW):
        rows.append({"type": ACTION_ROW, "components": buttons[start : start + _MAX_PER_ROW]})
    rows = rows[:_MAX_ROWS]
    return {"content": PANEL_CONTENT, "components": rows}


def build_modal_payload(template_key: str | None, template_label: str | None = None) -> dict:
    """Type-9 MODAL `data`: a single paragraph 'Describe your app' field. The
    custom_id carries the template key so the submit handler knows what to build."""
    key = template_key or ""
    what = template_label or template_key or "app"
    return {
        "title": f"Build: {what}"[:45],
        "custom_id": f"{BUILD_PREFIX}{key}",
        "components": [
            {
                "type": ACTION_ROW,
                "components": [
                    {
                        "type": TEXT_INPUT,
                        "custom_id": DESCRIPTION_INPUT_ID,
                        "label": "Describe your app",
                        "style": TEXT_PARAGRAPH,
                        "required": True,
                        "max_length": 4000,
                        "placeholder": "e.g. a portfolio site for Maya, a UX designer",
                    }
                ],
            }
        ],
    }


def is_panel_button(custom_id: str) -> bool:
    return custom_id.startswith(TEMPLATE_PREFIX)


def is_panel_modal(custom_id: str) -> bool:
    return custom_id.startswith(BUILD_PREFIX)


def template_key_from_button(custom_id: str) -> str | None:
    """Button custom_id -> template key. Bare prefix (Blank) -> None."""
    if not is_panel_button(custom_id):
        raise ValueError(f"not a panel button custom_id: {custom_id!r}")
    return custom_id[len(TEMPLATE_PREFIX):] or None


def template_key_from_modal(custom_id: str) -> str | None:
    """Modal custom_id -> template key. Bare prefix -> None."""
    if not is_panel_modal(custom_id):
        raise ValueError(f"not a panel modal custom_id: {custom_id!r}")
    return custom_id[len(BUILD_PREFIX):] or None


PUBLISH_PREFIX = "aiuibuild:publish:"  # ready-msg button -> aiuibuild:publish:<slug>


def build_ready_components(slug: str, preview_url: str = "") -> list[dict]:
    """Action row for the build-ready message: a green Publish button, plus an
    'Open preview' link button when a preview_url is available. Link buttons
    carry `url` and must NOT carry a custom_id."""
    buttons: list[dict] = [
        _button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS),
    ]
    if preview_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open preview", "url": preview_url})
    return [{"type": ACTION_ROW, "components": buttons}]


def is_publish_button(custom_id: str) -> bool:
    return custom_id.startswith(PUBLISH_PREFIX)


def slug_from_publish_button(custom_id: str) -> str:
    """Publish-button custom_id -> slug. Raises ValueError if not a publish id
    or if the slug portion is empty."""
    if not is_publish_button(custom_id):
        raise ValueError(f"not a publish button custom_id: {custom_id!r}")
    slug = custom_id[len(PUBLISH_PREFIX):]
    if not slug:
        raise ValueError(f"publish button custom_id has no slug: {custom_id!r}")
    return slug
