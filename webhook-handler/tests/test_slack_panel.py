"""Pure builders for the Slack App Builder panel + modal, and id parsing."""
import pytest
from handlers.slack_app_builder_panel import (
    build_panel_blocks, build_modal_view, description_from_view,
    is_panel_button, is_panel_modal,
    template_key_from_button, template_key_from_modal,
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_BLOCK_ID, DESCRIPTION_INPUT_ID,
)

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "\U0001f3a8", "description": "..."},
    {"key": "landing", "label": "Landing page", "emoji": "\U0001f680", "description": "..."},
    {"key": "dashboard", "label": "Dashboard", "emoji": "\U0001f4ca", "description": "..."},
]


def _buttons(blocks):
    return [el for b in blocks if b["type"] == "actions" for el in b["elements"]]


def test_panel_has_button_per_template_plus_blank():
    blocks = build_panel_blocks(_TEMPLATES)
    # first block is the header section
    assert blocks[0]["type"] == "section"
    buttons = _buttons(blocks)
    assert len(buttons) == len(_TEMPLATES) + 1
    ids = [b["action_id"] for b in buttons]
    assert f"{TEMPLATE_PREFIX}portfolio" in ids
    assert TEMPLATE_PREFIX in ids  # blank button carries the bare prefix


def test_panel_blocks_within_slack_limits():
    many = [{"key": f"t{i}", "label": f"T{i}", "emoji": "x"} for i in range(30)]
    blocks = build_panel_blocks(many)
    action_blocks = [b for b in blocks if b["type"] == "actions"]
    for b in action_blocks:
        assert len(b["elements"]) <= 5  # Slack actions block cap
    buttons = _buttons(blocks)
    assert len(buttons) <= 25
    assert TEMPLATE_PREFIX in [b["action_id"] for b in buttons]  # blank survives the cap


def test_panel_skips_keyless_rows():
    blocks = build_panel_blocks(
        [{"label": "no key", "emoji": "x"}, {"key": "ok", "label": "OK", "emoji": "y"}]
    )
    ids = [b["action_id"] for b in _buttons(blocks)]
    assert f"{TEMPLATE_PREFIX}ok" in ids
    assert TEMPLATE_PREFIX in ids


def test_modal_view_shape_and_channel_metadata():
    view = build_modal_view("portfolio", "Portfolio", channel_id="C123")
    assert view["type"] == "modal"
    assert view["callback_id"] == f"{BUILD_PREFIX}portfolio"
    assert view["private_metadata"] == "C123"  # channel travels through the modal
    assert len(view["title"]["text"]) <= 24
    block = view["blocks"][0]
    assert block["type"] == "input"
    assert block["block_id"] == DESCRIPTION_BLOCK_ID
    assert block["element"]["action_id"] == DESCRIPTION_INPUT_ID
    assert block["element"]["multiline"] is True


def test_modal_view_blank_key():
    view = build_modal_view(None)
    assert view["callback_id"] == BUILD_PREFIX
    assert view["private_metadata"] == ""


def test_modal_title_truncated_for_long_label():
    view = build_modal_view("x", "A very long template label that exceeds limit")
    assert len(view["title"]["text"]) <= 24


def test_description_from_view():
    view = {
        "state": {"values": {
            DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": "  a portfolio for Maya  "}}
        }}
    }
    assert description_from_view(view) == "a portfolio for Maya"
    assert description_from_view({}) == ""
    assert description_from_view({"state": {"values": {}}}) == ""


def test_id_parsers():
    assert is_panel_button(f"{TEMPLATE_PREFIX}portfolio")
    assert not is_panel_button("other:thing")
    assert not is_panel_button("")
    assert template_key_from_button(f"{TEMPLATE_PREFIX}portfolio") == "portfolio"
    assert template_key_from_button(TEMPLATE_PREFIX) is None
    assert is_panel_modal(f"{BUILD_PREFIX}portfolio")
    assert template_key_from_modal(f"{BUILD_PREFIX}portfolio") == "portfolio"
    assert template_key_from_modal(BUILD_PREFIX) is None


def test_parser_raises_on_wrong_prefix():
    with pytest.raises(ValueError):
        template_key_from_button(f"{BUILD_PREFIX}portfolio")
    with pytest.raises(ValueError):
        template_key_from_modal(f"{TEMPLATE_PREFIX}portfolio")
