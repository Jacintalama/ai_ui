from handlers import app_builder_panel as panel


def test_app_select_id_recognized():
    assert panel.is_app_select(panel.APP_SELECT_ID) is True
    assert panel.is_app_select("aiuibuild:publish:foo") is False


def test_status_button_roundtrip():
    cid = f"{panel.STATUS_PREFIX}my-coffee-shop"
    assert panel.is_status_button(cid) is True
    assert panel.slug_from_status_button(cid) == "my-coffee-shop"


def test_status_button_rejects_foreign_and_empty():
    assert panel.is_status_button("aiuibuild:publish:x") is False
    import pytest
    with pytest.raises(ValueError):
        panel.slug_from_status_button("aiuibuild:status:")  # empty slug


def test_build_apps_select_shape():
    rows = panel.build_apps_select_components([
        {"slug": "shop", "name": "My Shop", "public_url": "https://x"},
        {"slug": "port", "name": "Portfolio", "public_url": None},
    ])
    assert len(rows) == 1
    select = rows[0]["components"][0]
    assert select["type"] == panel.SELECT_MENU
    assert select["custom_id"] == panel.APP_SELECT_ID
    assert [o["value"] for o in select["options"]] == ["shop", "port"]
    assert select["options"][0]["label"] == "My Shop"


def test_build_apps_select_description_reflects_publish_state():
    rows = panel.build_apps_select_components([
        {"slug": "shop", "name": "My Shop", "public_url": "https://x"},
        {"slug": "port", "name": "Portfolio", "public_url": None},
    ])
    opts = rows[0]["components"][0]["options"]
    assert opts[0]["description"] == "published"
    assert opts[1]["description"] == "not published"


def test_build_apps_select_caps_at_25():
    projects = [{"slug": f"a{i}", "name": f"A{i}", "public_url": None} for i in range(40)]
    rows = panel.build_apps_select_components(projects)
    assert len(rows[0]["components"][0]["options"]) == 25


def _labels(rows):
    return [c.get("label") for c in rows[0]["components"]]


def test_project_menu_not_published():
    rows = panel.build_project_menu_components(
        "shop", published=False, public_url="", preview_url="https://prev/shop/")
    labels = _labels(rows)
    assert any("Enhance" in l for l in labels)
    assert any("Publish" in l for l in labels)
    assert any("Open preview" in l for l in labels)
    assert any("Status" in l for l in labels)
    assert not any("Unpublish" in l for l in labels)


def test_project_menu_published():
    rows = panel.build_project_menu_components(
        "shop", published=True, public_url="https://shop.live", preview_url="")
    labels = _labels(rows)
    assert any("Unpublish" in l for l in labels)
    assert any("Open live" in l for l in labels)
    # no standalone Publish button when published (Unpublish is the only *publish* word)
    assert not any(("Publish" in l and "Unpublish" not in l) for l in labels)


def test_project_menu_omits_link_when_url_missing():
    rows = panel.build_project_menu_components(
        "shop", published=False, public_url="", preview_url="")
    link_buttons = [c for c in rows[0]["components"] if c.get("style") == panel.STYLE_LINK]
    assert link_buttons == []


def test_project_menu_status_custom_id():
    rows = panel.build_project_menu_components("shop", published=True, public_url="https://x")
    status = [c for c in rows[0]["components"] if c.get("custom_id", "").startswith(panel.STATUS_PREFIX)]
    assert status and status[0]["custom_id"] == "aiuibuild:status:shop"
