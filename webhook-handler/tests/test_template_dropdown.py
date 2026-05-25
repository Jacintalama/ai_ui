"""App Builder panel: 25-button grid → a 'Pick a template' dropdown + Blank."""
from handlers import app_builder_panel as p

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "🎨", "description": "personal showcase"},
    {"key": "dashboard", "label": "Dashboard", "emoji": "📊", "description": "metrics view"},
]


def _selects(payload):
    return [c for row in payload["components"] for c in row["components"]
            if c.get("type") == p.SELECT_MENU]


def _buttons(payload):
    return [c for row in payload["components"] for c in row["components"]
            if c.get("type") == p.BUTTON]


def test_panel_uses_template_dropdown_plus_blank():
    payload = p.build_panel_payload(_TEMPLATES)
    selects = _selects(payload)
    assert len(selects) == 1
    sel = selects[0]
    assert sel["custom_id"] == p.TEMPLATE_SELECT_ID
    opts = {o["value"]: o for o in sel["options"]}
    assert "portfolio" in opts and "dashboard" in opts
    assert "Portfolio" in opts["portfolio"]["label"]
    assert "showcase" in opts["portfolio"]["description"]
    # Blank stays a button (bare TEMPLATE_PREFIX)
    assert p.TEMPLATE_PREFIX in {b.get("custom_id") for b in _buttons(payload)}


def test_panel_dropdown_caps_at_25():
    many = [{"key": f"t{i}", "label": f"T{i}", "emoji": "•", "description": "d"} for i in range(40)]
    sel = _selects(p.build_panel_payload(many))[0]
    assert len(sel["options"]) <= 25


def test_panel_skips_keyless_templates():
    payload = p.build_panel_payload([{"label": "no key"},
                                     {"key": "ok", "label": "OK", "emoji": "x", "description": "d"}])
    vals = {o["value"] for o in _selects(payload)[0]["options"]}
    assert vals == {"ok"}


def test_is_template_select():
    assert p.is_template_select(p.TEMPLATE_SELECT_ID)
    assert not p.is_template_select("aiuibuild:tpl:portfolio")
