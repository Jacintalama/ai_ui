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
from handlers.app_builder_panel import (
    build_template_picker_components,
    PANEL_NEW_ID, PANEL_MYAPPS_ID, TEMPLATE_SELECT_ID,
    is_panel_new, is_panel_myapps, SELECT_MENU,
)

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "\U0001f3a8", "description": "..."},
    {"key": "landing", "label": "Landing page", "emoji": "\U0001f680", "description": "..."},
    {"key": "dashboard", "label": "Dashboard", "emoji": "\U0001f4ca", "description": "..."},
]


def test_template_picker_rows_within_discord_limits():
    many = [{"key": f"t{i}", "label": f"T{i}", "emoji": "x"} for i in range(30)]
    rows = build_template_picker_components(many)
    assert len(rows) <= 5
    for row in rows:
        assert row["type"] == ACTION_ROW
        assert len(row["components"]) <= 5
    total = sum(len(r["components"]) for r in rows)
    assert total <= 25
    # Blank must always appear, even under the 25-option cap
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
    rows = build_ready_components("portfolio-ab12", "https://x/preview/portfolio-ab12/",
                                  owner="alice@example.com")
    assert rows[0]["type"] == ACTION_ROW
    btns = rows[0]["components"]
    assert btns[0]["custom_id"] == f"{PUBLISH_PREFIX}portfolio-ab12"
    assert btns[0]["style"] == STYLE_SUCCESS
    # Enhance is gone — replaced by the Visual Editor link.
    assert not any(b.get("custom_id", "").startswith(ENHANCE_PREFIX) for b in btns)
    assert any(b.get("url") == "https://x/preview/portfolio-ab12/" for b in btns)
    assert any("Visual Editor" in b.get("label", "") for b in btns)


def test_ready_components_without_preview_has_publish_and_visual_editor():
    rows = build_ready_components("slug-1", "", owner="alice@example.com")
    btns = rows[0]["components"]
    # Publish + Visual Editor (no preview link without a preview_url)
    assert len(btns) == 2
    assert btns[0]["custom_id"] == f"{PUBLISH_PREFIX}slug-1"
    assert btns[1]["style"] == STYLE_LINK
    assert "Visual Editor" in btns[1]["label"]


def test_publish_button_parsers():
    assert is_publish_button(f"{PUBLISH_PREFIX}slug-1")
    assert not is_publish_button("aiuibuild:tpl:portfolio")
    assert slug_from_publish_button(f"{PUBLISH_PREFIX}slug-1") == "slug-1"
    with pytest.raises(ValueError):
        slug_from_publish_button("aiuibuild:tpl:x")


def test_connect_components_and_resume_parsers():
    from handlers.app_builder_panel import (
        build_connect_components, is_connect_resume, token_from_connect_resume,
        CONNECT_RESUME_PREFIX, STYLE_LINK,
    )
    rows = build_connect_components(
        token="tok123", links=[("Gmail", "https://x/auth?state=a"), ("Drive", "https://x/auth?state=b")])
    btns = [b for row in rows for b in row["components"]]
    # Two link buttons (one per connector) + the 'I've connected' resume button.
    assert sum(1 for b in btns if b.get("style") == STYLE_LINK and "url" in b) == 2
    resume = next(b for b in btns if b.get("custom_id", "").startswith(CONNECT_RESUME_PREFIX))
    assert is_connect_resume(resume["custom_id"])
    assert token_from_connect_resume(resume["custom_id"]) == "tok123"
    with pytest.raises(ValueError):
        token_from_connect_resume("aiuisched:confirm:tok123")
    with pytest.raises(ValueError):
        slug_from_publish_button(PUBLISH_PREFIX)  # bare prefix, no slug


def test_published_components_have_visual_editor_and_unpublish_and_live_link():
    rows = build_published_components(
        "slug-1", "https://slug-1.ai-ui.coolestdomain.win/", owner="alice@example.com")
    btns = rows[0]["components"]
    ids = [b.get("custom_id") for b in btns]
    assert f"{ENHANCE_PREFIX}slug-1" not in ids          # Enhance replaced
    assert any("Visual Editor" in b.get("label", "") for b in btns)
    assert f"{UNPUBLISH_PREFIX}slug-1" in ids
    live = [b for b in btns
            if b.get("url") == "https://slug-1.ai-ui.coolestdomain.win/"][0]
    assert "custom_id" not in live
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


_ENTRY_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "🎨", "description": "A personal site"},
]


def test_entry_panel_has_two_buttons():
    payload = build_panel_payload(_ENTRY_TEMPLATES)
    buttons = [c for row in payload["components"] for c in row["components"]
               if c["type"] == BUTTON]
    ids = {b["custom_id"] for b in buttons}
    assert ids == {PANEL_NEW_ID, PANEL_MYAPPS_ID}
    assert not any(c["type"] == SELECT_MENU
                   for row in payload["components"] for c in row["components"])


def test_template_picker_has_dropdown_and_blank():
    comps = build_template_picker_components(_ENTRY_TEMPLATES)
    flat = [c for row in comps for c in row["components"]]
    assert any(c["type"] == SELECT_MENU and c["custom_id"] == TEMPLATE_SELECT_ID
               for c in flat)
    assert any(c["type"] == BUTTON and c["custom_id"] == TEMPLATE_PREFIX
               for c in flat)  # Blank


def test_panel_id_predicates():
    assert is_panel_new(PANEL_NEW_ID) and not is_panel_new("x")
    assert is_panel_myapps(PANEL_MYAPPS_ID) and not is_panel_myapps("x")


# --- Delete (with confirm) in the per-app "My apps" menu ---
from handlers.app_builder_panel import (
    build_project_menu_components,
    build_delete_confirm_components,
    DELETE_PREFIX, DEL_CONFIRM_PREFIX, DEL_CANCEL_PREFIX,
    is_app_delete, slug_from_delete_button,
    is_del_confirm, slug_from_del_confirm,
    is_del_cancel, slug_from_del_cancel,
)


def _flat_buttons(rows):
    return [c for row in rows for c in row["components"]]


def test_project_menu_has_delete_button_draft():
    rows = build_project_menu_components(
        "shop", published=False, preview_url="https://x/tasks/preview-app/shop/")
    btns = _flat_buttons(rows)
    ids = [b.get("custom_id") for b in btns]
    assert f"{DELETE_PREFIX}shop" in ids
    # Delete button is danger style
    delete = next(b for b in btns if b.get("custom_id") == f"{DELETE_PREFIX}shop")
    assert delete["style"] == STYLE_DANGER
    # the open/preview link button is still present
    assert any(b.get("style") == STYLE_LINK and b.get("url") for b in btns)
    # ≤5 buttons per action row
    for row in rows:
        assert len(row["components"]) <= 5


def test_project_menu_has_delete_button_published():
    rows = build_project_menu_components(
        "shop", published=True, public_url="https://shop.example.com/")
    btns = _flat_buttons(rows)
    ids = [b.get("custom_id") for b in btns]
    assert f"{DELETE_PREFIX}shop" in ids
    # the open/live link button is still present
    assert any(b.get("style") == STYLE_LINK and b.get("url") for b in btns)
    # ≤5 buttons per action row (published row may overflow Delete to row 2)
    for row in rows:
        assert len(row["components"]) <= 5


def test_delete_confirm_components_shape():
    rows = build_delete_confirm_components("shop")
    btns = _flat_buttons(rows)
    ids = [b["custom_id"] for b in btns]
    assert f"{DEL_CONFIRM_PREFIX}shop" in ids
    assert f"{DEL_CANCEL_PREFIX}shop" in ids
    confirm = next(b for b in btns if b["custom_id"] == f"{DEL_CONFIRM_PREFIX}shop")
    assert confirm["style"] == STYLE_DANGER
    for row in rows:
        assert len(row["components"]) <= 5


def test_delete_parsers_roundtrip():
    assert is_app_delete(f"{DELETE_PREFIX}s") and slug_from_delete_button(f"{DELETE_PREFIX}s") == "s"
    assert is_del_confirm(f"{DEL_CONFIRM_PREFIX}s") and slug_from_del_confirm(f"{DEL_CONFIRM_PREFIX}s") == "s"
    assert is_del_cancel(f"{DEL_CANCEL_PREFIX}s") and slug_from_del_cancel(f"{DEL_CANCEL_PREFIX}s") == "s"
    # delete predicate must not match the confirm/cancel ids (disjoint routing)
    assert not is_app_delete(f"{DEL_CONFIRM_PREFIX}s")
    assert not is_app_delete(f"{DEL_CANCEL_PREFIX}s")
    for fn, pref in [(slug_from_delete_button, DELETE_PREFIX),
                     (slug_from_del_confirm, DEL_CONFIRM_PREFIX),
                     (slug_from_del_cancel, DEL_CANCEL_PREFIX)]:
        with pytest.raises(ValueError):
            fn(pref)  # bare prefix, empty slug
