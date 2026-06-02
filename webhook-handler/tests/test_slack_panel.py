"""Pure builders for the Slack App Builder panel + modal, and id parsing."""
import pytest
from handlers.slack_app_builder_panel import (
    build_panel_blocks, build_modal_view, description_from_view,
    is_panel_button, is_panel_modal,
    template_key_from_button, template_key_from_modal,
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_BLOCK_ID, DESCRIPTION_INPUT_ID,
    TEMPLATE_SELECT_ACTION_ID, BLANK_ACTION_ID, FRIENDLY_DESCRIPTIONS,
    # B5
    PUBLISH_PREFIX, ENHANCE_PREFIX, ENHANCE_MODAL_PREFIX,
    UNPUBLISH_PREFIX, STATUS_PREFIX,
    is_action, slug_from_action, is_enhance_modal, slug_from_enhance_modal,
    # B6
    build_ready_attachment, build_published_attachment,
    COLOR_READY, COLOR_PUBLISHED,
    # B7
    build_apps_list_blocks, build_enhance_modal_view, enhance_text_from_view,
)

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "\U0001f3a8", "description": "..."},
    {"key": "landing", "label": "Landing page", "emoji": "\U0001f680", "description": "..."},
    {"key": "dashboard", "label": "Dashboard", "emoji": "\U0001f4ca", "description": "..."},
]


# ---------------------------------------------------------------------------
# B4 — dropdown panel
# ---------------------------------------------------------------------------

def _static_selects(blocks):
    return [el for b in blocks if b["type"] == "actions"
            for el in b["elements"] if el.get("type") == "static_select"]


def _action_buttons(blocks):
    return [el for b in blocks if b["type"] == "actions"
            for el in b["elements"] if el.get("type") == "button"]


def test_panel_has_static_select_with_all_templates():
    blocks = build_panel_blocks(_TEMPLATES)
    assert blocks[0]["type"] == "section"
    selects = _static_selects(blocks)
    assert len(selects) == 1
    select = selects[0]
    assert select["action_id"] == TEMPLATE_SELECT_ACTION_ID
    option_values = [o["value"] for o in select["options"]]
    assert f"{TEMPLATE_PREFIX}portfolio" in option_values
    assert f"{TEMPLATE_PREFIX}landing" in option_values
    assert f"{TEMPLATE_PREFIX}dashboard" in option_values


def test_panel_blank_button_present():
    blocks = build_panel_blocks(_TEMPLATES)
    buttons = _action_buttons(blocks)
    blank_ids = [b["action_id"] for b in buttons]
    assert BLANK_ACTION_ID in blank_ids


def test_panel_options_carry_description():
    # Each template's one-line description appears under the option so users
    # understand what the template builds.
    tpls = [
        {"key": "landing", "label": "Landing page", "description": "marketing / product page"},
        {"key": "weird-key", "label": "Weird", "description": "catalog only"},  # not in override map
        {"key": "blank2", "label": "No-desc"},  # no description anywhere
    ]
    selects = _static_selects(build_panel_blocks(tpls))
    by_value = {o["value"]: o for o in selects[0]["options"]}
    # A known template uses the plain-language override, not the terse catalog text.
    landing = by_value[f"{TEMPLATE_PREFIX}landing"]
    assert landing["description"]["type"] == "plain_text"
    assert landing["description"]["text"] == FRIENDLY_DESCRIPTIONS["landing"]
    assert landing["description"]["text"] != "marketing / product page"
    # An unknown key falls back to the catalog's own description.
    assert by_value[f"{TEMPLATE_PREFIX}weird-key"]["description"]["text"] == "catalog only"
    # No description anywhere -> field omitted (no crash).
    assert "description" not in by_value[f"{TEMPLATE_PREFIX}blank2"]


def test_friendly_descriptions_within_slack_limit():
    # Slack caps option descriptions at 75 chars.
    assert all(len(v) <= 75 for v in FRIENDLY_DESCRIPTIONS.values())


def test_panel_skips_keyless_rows():
    blocks = build_panel_blocks(
        [{"label": "no key", "emoji": "x"}, {"key": "ok", "label": "OK", "emoji": "y"}]
    )
    selects = _static_selects(blocks)
    assert len(selects) == 1
    option_values = [o["value"] for o in selects[0]["options"]]
    assert f"{TEMPLATE_PREFIX}ok" in option_values
    # keyless row not included
    assert not any("no key" in v for v in option_values)


def test_panel_30_templates_all_appear():
    many = [{"key": f"t{i}", "label": f"T{i}"} for i in range(30)]
    blocks = build_panel_blocks(many)
    selects = _static_selects(blocks)
    assert len(selects) == 1
    option_values = [o["value"] for o in selects[0]["options"]]
    # all 30 should appear — no truncation (static_select supports up to 100)
    for i in range(30):
        assert f"{TEMPLATE_PREFIX}t{i}" in option_values


def test_panel_empty_templates_has_blank_option_in_select():
    blocks = build_panel_blocks([])
    selects = _static_selects(blocks)
    assert len(selects) == 1
    assert selects[0]["options"][0]["value"] == TEMPLATE_PREFIX


def test_panel_option_text_truncated_to_75():
    long_label = "A" * 100
    blocks = build_panel_blocks([{"key": "x", "label": long_label}])
    selects = _static_selects(blocks)
    for opt in selects[0]["options"]:
        assert len(opt["text"]["text"]) <= 75


# ---------------------------------------------------------------------------
# Existing tests kept (modal + id parsers — unchanged)
# ---------------------------------------------------------------------------

def test_modal_view_shape_and_channel_metadata():
    view = build_modal_view("portfolio", "Portfolio", channel_id="C123")
    assert view["type"] == "modal"
    assert view["callback_id"] == f"{BUILD_PREFIX}portfolio"
    assert view["private_metadata"] == "C123"
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


# ---------------------------------------------------------------------------
# B5 — management action_id parsers
# ---------------------------------------------------------------------------

def test_is_action_true_for_matching_prefix():
    assert is_action(f"{PUBLISH_PREFIX}my-app", PUBLISH_PREFIX)
    assert is_action(f"{ENHANCE_PREFIX}my-app", ENHANCE_PREFIX)
    assert is_action(f"{UNPUBLISH_PREFIX}my-app", UNPUBLISH_PREFIX)
    assert is_action(f"{STATUS_PREFIX}my-app", STATUS_PREFIX)


def test_is_action_false_for_wrong_prefix():
    assert not is_action(f"{ENHANCE_PREFIX}my-app", PUBLISH_PREFIX)
    assert not is_action("", PUBLISH_PREFIX)
    assert not is_action("other:thing", ENHANCE_PREFIX)


def test_slug_from_action_round_trip():
    for prefix in (PUBLISH_PREFIX, ENHANCE_PREFIX, UNPUBLISH_PREFIX, STATUS_PREFIX):
        assert slug_from_action(f"{prefix}my-app", prefix) == "my-app"


def test_slug_from_action_raises_wrong_prefix():
    with pytest.raises(ValueError):
        slug_from_action(f"{ENHANCE_PREFIX}my-app", PUBLISH_PREFIX)
    with pytest.raises(ValueError):
        slug_from_action("", PUBLISH_PREFIX)


def test_enhance_modal_parser_round_trip():
    cb = f"{ENHANCE_MODAL_PREFIX}my-app"
    assert is_enhance_modal(cb)
    assert slug_from_enhance_modal(cb) == "my-app"


def test_enhance_modal_parser_false_for_wrong_prefix():
    assert not is_enhance_modal(f"{BUILD_PREFIX}my-app")
    assert not is_enhance_modal("")


def test_enhance_modal_parser_raises_wrong_prefix():
    with pytest.raises(ValueError):
        slug_from_enhance_modal(f"{BUILD_PREFIX}my-app")


# ---------------------------------------------------------------------------
# B6 — build-ready + published card attachments
# ---------------------------------------------------------------------------

def test_build_ready_attachment_shape():
    att = build_ready_attachment("my-app")
    assert att["color"] == COLOR_READY
    blocks = att["blocks"]
    # section block with slug in text
    assert any(b["type"] == "section" and "my-app" in b["text"]["text"] for b in blocks)
    # actions block
    actions = [b for b in blocks if b["type"] == "actions"]
    assert len(actions) == 1
    elements = actions[0]["elements"]
    action_ids = [e.get("action_id") for e in elements]
    assert f"{PUBLISH_PREFIX}my-app" in action_ids
    assert f"{ENHANCE_PREFIX}my-app" in action_ids


def test_build_ready_no_link_when_no_url():
    att = build_ready_attachment("my-app")
    elements = att["blocks"][-1]["elements"]
    assert len(elements) == 2                      # Publish + Enhance only
    assert all(e.get("url") is None for e in elements)


def test_build_ready_attachment_with_preview_url():
    att = build_ready_attachment("my-app", preview_url="https://example.com/preview")
    elements = att["blocks"][-1]["elements"]
    link_btns = [e for e in elements if e.get("url") == "https://example.com/preview"]
    assert len(link_btns) == 1
    assert link_btns[0]["text"]["text"] == "Open preview"


def test_build_published_attachment_shape():
    att = build_published_attachment("my-app")
    assert att["color"] == COLOR_PUBLISHED
    blocks = att["blocks"]
    actions = [b for b in blocks if b["type"] == "actions"]
    elements = actions[0]["elements"]
    action_ids = [e.get("action_id") for e in elements]
    assert f"{ENHANCE_PREFIX}my-app" in action_ids
    assert f"{UNPUBLISH_PREFIX}my-app" in action_ids


def test_build_published_attachment_with_public_url():
    att = build_published_attachment("my-app", public_url="https://example.com/live")
    elements = att["blocks"][-1]["elements"]
    link_btns = [e for e in elements if e.get("url") == "https://example.com/live"]
    assert len(link_btns) == 1
    assert link_btns[0]["text"]["text"] == "Open"


def test_build_published_attachment_no_link_when_no_url():
    att = build_published_attachment("my-app")
    elements = att["blocks"][-1]["elements"]
    assert all(e.get("url") is None for e in elements)


def test_attachment_colors_are_distinct():
    assert COLOR_READY != COLOR_PUBLISHED


# ---------------------------------------------------------------------------
# B7 — app-list blocks + enhance modal
# ---------------------------------------------------------------------------

_APPS = [
    {"slug": "my-app", "published": False},
    {"slug": "live-app", "published": True},
]


def _section_texts(blocks):
    return [b["text"]["text"] for b in blocks if b["type"] == "section"]


def _all_action_ids(blocks):
    return [el.get("action_id") for b in blocks if b["type"] == "actions"
            for el in b["elements"] if el.get("action_id")]


def test_apps_list_draft_has_publish_button():
    blocks = build_apps_list_blocks([{"slug": "draft-app", "published": False}])
    ids = _all_action_ids(blocks)
    assert f"{PUBLISH_PREFIX}draft-app" in ids


def test_apps_list_published_has_unpublish_button():
    blocks = build_apps_list_blocks([{"slug": "live-app", "published": True}])
    ids = _all_action_ids(blocks)
    assert f"{UNPUBLISH_PREFIX}live-app" in ids


def test_apps_list_both_have_status_and_enhance():
    blocks = build_apps_list_blocks(_APPS)
    ids = _all_action_ids(blocks)
    assert f"{STATUS_PREFIX}my-app" in ids
    assert f"{ENHANCE_PREFIX}my-app" in ids
    assert f"{STATUS_PREFIX}live-app" in ids
    assert f"{ENHANCE_PREFIX}live-app" in ids


def test_apps_list_empty_shows_no_apps_message():
    blocks = build_apps_list_blocks([])
    texts = _section_texts(blocks)
    assert any("no apps" in t.lower() for t in texts)


def test_apps_list_capped_at_10():
    many = [{"slug": f"app{i}", "published": False} for i in range(15)]
    blocks = build_apps_list_blocks(many)
    # only 10 apps' status buttons present
    ids = _all_action_ids(blocks)
    status_ids = [i for i in ids if i.startswith(STATUS_PREFIX)]
    assert len(status_ids) == 10


def test_apps_list_more_than_10_shows_context_block():
    many = [{"slug": f"app{i}", "published": False} for i in range(15)]
    blocks = build_apps_list_blocks(many)
    context_blocks = [b for b in blocks if b["type"] == "context"]
    assert len(context_blocks) >= 1
    text = context_blocks[0]["elements"][0]["text"]
    assert "10" in text


def test_apps_list_skips_slugless_apps():
    """Apps with no/empty slug must be silently dropped (empty slug => bare action_id prefix)."""
    apps = [{"slug": "", "published": False}, {"slug": "good-app", "published": False}]
    blocks = build_apps_list_blocks(apps)
    ids = _all_action_ids(blocks)
    # only the valid app's action_ids should appear
    assert any(i.endswith("good-app") for i in ids)
    # no bare-prefix action_ids (e.g. "aiuibuild:status:" with nothing after)
    assert not any(i in (STATUS_PREFIX, PUBLISH_PREFIX, ENHANCE_PREFIX, UNPUBLISH_PREFIX)
                   for i in ids)


def test_enhance_modal_view_shape():
    view = build_enhance_modal_view("my-app")
    assert view["type"] == "modal"
    assert view["callback_id"] == f"{ENHANCE_MODAL_PREFIX}my-app"
    assert view["private_metadata"] == "my-app"
    assert len(view["title"]["text"]) <= 24
    assert view["submit"]["text"] == "Apply"
    assert view["close"]["text"] == "Cancel"
    block = view["blocks"][0]
    assert block["block_id"] == "enhance_block"
    assert block["element"]["action_id"] == "enhance_input"
    assert block["element"]["multiline"] is True
    assert block["element"]["max_length"] == 3000


def test_enhance_modal_slug_in_callback_and_metadata():
    view = build_enhance_modal_view("another-slug")
    assert "another-slug" in view["callback_id"]
    assert view["private_metadata"] == "another-slug"


def test_enhance_modal_title_truncated_for_long_slug():
    view = build_enhance_modal_view("a-very-long-slug-exceeding-limit")
    assert len(view["title"]["text"]) <= 24
    assert view["private_metadata"] == "a-very-long-slug-exceeding-limit"


def test_enhance_text_from_view_extracts_value():
    view = {
        "state": {"values": {
            "enhance_block": {"enhance_input": {"value": "  make it dark mode  "}}
        }}
    }
    assert enhance_text_from_view(view) == "make it dark mode"


def test_enhance_text_from_view_empty_fallback():
    assert enhance_text_from_view({}) == ""
    assert enhance_text_from_view({"state": {"values": {}}}) == ""
