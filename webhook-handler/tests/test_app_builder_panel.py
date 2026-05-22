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
