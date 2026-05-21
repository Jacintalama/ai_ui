"""Pure builders for the App Builder channel panel + modal, and custom_id parsing."""
import pytest
from handlers.app_builder_panel import (
    build_panel_payload, build_modal_payload,
    is_panel_button, is_panel_modal,
    template_key_from_button, template_key_from_modal,
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_INPUT_ID,
    ACTION_ROW, TEXT_INPUT, STYLE_SECONDARY,
)

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "\U0001f3a8", "description": "..."},
    {"key": "landing", "label": "Landing page", "emoji": "\U0001f680", "description": "..."},
    {"key": "dashboard", "label": "Dashboard", "emoji": "\U0001f4ca", "description": "..."},
]


def test_panel_has_button_per_template_plus_blank():
    payload = build_panel_payload(_TEMPLATES)
    buttons = [c for row in payload["components"] for c in row["components"]]
    assert len(buttons) == len(_TEMPLATES) + 1
    ids = [b["custom_id"] for b in buttons]
    assert f"{TEMPLATE_PREFIX}portfolio" in ids
    assert TEMPLATE_PREFIX in ids  # blank button has the bare prefix
    blank = next(b for b in buttons if b["custom_id"] == TEMPLATE_PREFIX)
    assert blank["style"] == STYLE_SECONDARY


def test_panel_rows_within_discord_limits():
    many = [{"key": f"t{i}", "label": f"T{i}", "emoji": "x"} for i in range(30)]
    payload = build_panel_payload(many)
    rows = payload["components"]
    assert len(rows) <= 5
    for row in rows:
        assert row["type"] == ACTION_ROW
        assert len(row["components"]) <= 5
    total = sum(len(r["components"]) for r in rows)
    assert total <= 25
    # Blank must always appear, even under the 25-button cap
    all_ids = [c["custom_id"] for row in rows for c in row["components"]]
    assert TEMPLATE_PREFIX in all_ids


def test_panel_skips_keyless_rows():
    payload = build_panel_payload(
        [{"label": "no key", "emoji": "x"}, {"key": "ok", "label": "OK", "emoji": "y"}]
    )
    ids = [c["custom_id"] for row in payload["components"] for c in row["components"]]
    assert f"{TEMPLATE_PREFIX}ok" in ids
    assert TEMPLATE_PREFIX in ids  # blank still present


def test_modal_payload_shape():
    data = build_modal_payload("portfolio", "Portfolio")
    assert data["custom_id"] == f"{BUILD_PREFIX}portfolio"
    row = data["components"][0]
    assert row["type"] == ACTION_ROW
    inp = row["components"][0]
    assert inp["type"] == TEXT_INPUT
    assert inp["custom_id"] == DESCRIPTION_INPUT_ID
    assert inp["required"] is True


def test_modal_payload_blank_key():
    data = build_modal_payload(None)
    assert data["custom_id"] == BUILD_PREFIX  # empty key


def test_custom_id_parsers():
    assert is_panel_button(f"{TEMPLATE_PREFIX}portfolio")
    assert not is_panel_button("other:thing")
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
