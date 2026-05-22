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
