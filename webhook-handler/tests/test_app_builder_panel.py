"""Pure builders for the App Builder channel panel + modal, and custom_id parsing."""
import pytest
from handlers.app_builder_panel import (
    build_panel_payload, build_modal_payload,
    is_panel_button, is_panel_modal,
    template_key_from_button, template_key_from_modal,
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_INPUT_ID,
    ACTION_ROW, TEXT_INPUT, STYLE_SECONDARY,
    build_ready_components, is_publish_button, slug_from_publish_button,
    PUBLISH_PREFIX, STYLE_SUCCESS, STYLE_LINK, BUTTON,
)
from handlers.app_builder_panel import (
    build_published_components, build_enhance_modal,
    is_enhance_button, slug_from_enhance_button,
    is_unpublish_button, slug_from_unpublish_button,
    is_enhance_modal, slug_from_enhance_modal,
    ENHANCE_PREFIX, UNPUBLISH_PREFIX, ENHANCE_MODAL_PREFIX,
    STYLE_PRIMARY, STYLE_DANGER, TEXT_INPUT,
)

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "\U0001f3a8", "description": "..."},
    {"key": "landing", "label": "Landing page", "emoji": "\U0001f680", "description": "..."},
    {"key": "dashboard", "label": "Dashboard", "emoji": "\U0001f4ca", "description": "..."},
]


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


def test_ready_components_has_publish_and_preview():
    rows = build_ready_components("portfolio-ab12", "https://x/preview/portfolio-ab12/")
    assert rows[0]["type"] == ACTION_ROW
    btns = rows[0]["components"]
    pub = btns[0]
    assert pub["custom_id"] == f"{PUBLISH_PREFIX}portfolio-ab12"
    assert pub["style"] == STYLE_SUCCESS
    # Enhance button is now the second button
    enhance = btns[1]
    assert enhance["custom_id"] == f"{ENHANCE_PREFIX}portfolio-ab12"
    assert enhance["style"] == STYLE_PRIMARY
    # Link button is now the third button
    link = btns[2]
    assert link["style"] == STYLE_LINK
    assert link["url"] == "https://x/preview/portfolio-ab12/"
    assert "custom_id" not in link  # link buttons must not carry a custom_id


def test_ready_components_without_preview_has_publish_and_enhance():
    rows = build_ready_components("slug-1", "")
    btns = rows[0]["components"]
    assert len(btns) == 2
    assert btns[0]["custom_id"] == f"{PUBLISH_PREFIX}slug-1"
    assert btns[1]["custom_id"] == f"{ENHANCE_PREFIX}slug-1"


def test_publish_button_parsers():
    assert is_publish_button(f"{PUBLISH_PREFIX}slug-1")
    assert not is_publish_button("aiuibuild:tpl:portfolio")
    assert slug_from_publish_button(f"{PUBLISH_PREFIX}slug-1") == "slug-1"
    with pytest.raises(ValueError):
        slug_from_publish_button("aiuibuild:tpl:x")
    with pytest.raises(ValueError):
        slug_from_publish_button(PUBLISH_PREFIX)  # bare prefix, no slug


def test_published_components_have_enhance_and_unpublish_and_live_link():
    rows = build_published_components("slug-1", "https://slug-1.ai-ui.coolestdomain.win/")
    btns = rows[0]["components"]
    ids = [b.get("custom_id") for b in btns]
    assert f"{ENHANCE_PREFIX}slug-1" in ids
    assert f"{UNPUBLISH_PREFIX}slug-1" in ids
    link = [b for b in btns if b["style"] == STYLE_LINK][0]
    assert link["url"] == "https://slug-1.ai-ui.coolestdomain.win/"
    assert "custom_id" not in link
    unpub = [b for b in btns if b.get("custom_id") == f"{UNPUBLISH_PREFIX}slug-1"][0]
    assert unpub["style"] == STYLE_DANGER


def test_enhance_modal_shape():
    data = build_enhance_modal("slug-1")
    assert data["custom_id"] == f"{ENHANCE_MODAL_PREFIX}slug-1"
    inp = data["components"][0]["components"][0]
    assert inp["type"] == TEXT_INPUT
    assert inp["custom_id"] == "change"
    assert inp["required"] is True


def test_new_parsers():
    assert is_enhance_button(f"{ENHANCE_PREFIX}s") and slug_from_enhance_button(f"{ENHANCE_PREFIX}s") == "s"
    assert is_unpublish_button(f"{UNPUBLISH_PREFIX}s") and slug_from_unpublish_button(f"{UNPUBLISH_PREFIX}s") == "s"
    assert is_enhance_modal(f"{ENHANCE_MODAL_PREFIX}s") and slug_from_enhance_modal(f"{ENHANCE_MODAL_PREFIX}s") == "s"
    for fn, pref in [(slug_from_enhance_button, ENHANCE_PREFIX),
                     (slug_from_unpublish_button, UNPUBLISH_PREFIX),
                     (slug_from_enhance_modal, ENHANCE_MODAL_PREFIX)]:
        with pytest.raises(ValueError):
            fn(pref)  # bare prefix, empty slug
    # Wrong-prefix custom_ids must also raise (matches the publish parser test).
    with pytest.raises(ValueError):
        slug_from_enhance_button(f"{UNPUBLISH_PREFIX}slug")
    with pytest.raises(ValueError):
        slug_from_unpublish_button(f"{ENHANCE_PREFIX}slug")
    with pytest.raises(ValueError):
        slug_from_enhance_modal(f"{ENHANCE_PREFIX}slug")


def test_panel_content_mentions_private_space():
    from handlers.app_builder_panel import PANEL_CONTENT
    assert "private" in PANEL_CONTENT.lower()
