"""Tests for webhook-handler/handlers/video_panel.py — pure builders and custom_id helpers."""
import pytest
from handlers.video_panel import (
    # builders
    build_video_panel, build_details_modal, build_refine_modal,
    build_style_select, build_voice_select,
    build_done_components, build_proposal_components,
    build_video_embed,
    # constants
    NEW_ID, LIST_ID,
    STYLE_PREFIX, VOICE_PREFIX, GENERATE_PREFIX, DETAILS_PREFIX, DETAILS_MODAL_PREFIX,
    REFINE_PREFIX, REFINE_MODAL_PREFIX, APPLY_PREFIX, VERSION_PREFIX,
    TITLE_INPUT, PROMPT_INPUT, REFINE_INPUT,
    STYLES,
    # predicates
    is_vid_new, is_vid_list, is_vid_details, is_vid_details_modal,
    is_vid_style, is_vid_voice, is_vid_generate,
    is_vid_refine, is_vid_refine_modal, is_vid_apply, is_vid_version,
    # extractors
    job_from_style, job_from_voice, job_from_generate, job_from_details, job_from_details_modal,
    job_from_refine, job_from_refine_modal, job_from_apply, job_from_version,
)
from handlers.app_builder_panel import ACTION_ROW, BUTTON, SELECT_MENU, TEXT_INPUT
from handlers import video_panel as vp


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

def test_panel_has_new_and_list_buttons():
    payload = build_video_panel()
    buttons = [c for row in payload["components"] for c in row["components"]
               if c.get("type") == BUTTON]
    ids = {b["custom_id"] for b in buttons}
    assert NEW_ID in ids
    assert LIST_ID in ids
    assert len(ids) == 2


def test_panel_rows_are_action_rows():
    payload = build_video_panel()
    for row in payload["components"]:
        assert row["type"] == ACTION_ROW


# ---------------------------------------------------------------------------
# New-video modal
# ---------------------------------------------------------------------------

def test_details_modal_custom_id_and_inputs():
    modal = build_details_modal("job-d1")
    assert modal["custom_id"] == f"{DETAILS_MODAL_PREFIX}job-d1"
    inputs = [c for row in modal["components"] for c in row["components"]
              if c.get("type") == TEXT_INPUT]
    input_ids = [inp["custom_id"] for inp in inputs]
    assert input_ids == [TITLE_INPUT, PROMPT_INPUT]
    by_id = {inp["custom_id"]: inp for inp in inputs}
    assert by_id[TITLE_INPUT].get("required") is False
    assert by_id[PROMPT_INPUT].get("required") is True


def test_details_prefix_predicates_disjoint():
    assert is_vid_details(f"{DETAILS_PREFIX}j1") is True
    assert is_vid_details(f"{DETAILS_MODAL_PREFIX}j1") is False
    assert is_vid_details_modal(f"{DETAILS_MODAL_PREFIX}j1") is True
    assert is_vid_details_modal(f"{DETAILS_PREFIX}j1") is False
    assert job_from_details(f"{DETAILS_PREFIX}j1") == "j1"
    assert job_from_details_modal(f"{DETAILS_MODAL_PREFIX}j1") == "j1"


# ---------------------------------------------------------------------------
# Style select
# ---------------------------------------------------------------------------

def test_style_select_has_three_options():
    sel = build_style_select("job-1")
    assert sel["type"] == SELECT_MENU
    assert sel["custom_id"] == f"{STYLE_PREFIX}job-1"
    assert len(sel["options"]) == len(STYLES)


def test_style_select_option_values_match_style_keys():
    sel = build_style_select("job-2")
    values = {opt["value"] for opt in sel["options"]}
    expected = {key for key, _, _ in STYLES}
    assert values == expected


def test_style_select_default_is_clean_product_demo():
    sel = build_style_select("job-3")
    defaults = [opt for opt in sel["options"] if opt.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["value"] == "clean_product_demo"


def test_style_select_custom_default():
    sel = build_style_select("job-4", current="cinematic")
    defaults = [opt for opt in sel["options"] if opt.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["value"] == "cinematic"


# ---------------------------------------------------------------------------
# Voice select
# ---------------------------------------------------------------------------

_VOICES = [
    {"id": "amy", "label": "Amy", "accent": "US", "gender": "female"},
    {"id": "josh", "label": "Josh", "accent": "US", "gender": "male"},
    {"id": "bella", "label": "Bella", "accent": "UK", "gender": "female"},
]


def test_voice_select_builds_from_catalog():
    sel = build_voice_select("job-5", _VOICES)
    assert sel["type"] == SELECT_MENU
    assert sel["custom_id"] == f"{VOICE_PREFIX}job-5"
    assert len(sel["options"]) == len(_VOICES)


def test_voice_select_default():
    sel = build_voice_select("job-6", _VOICES, current="josh")
    defaults = [opt for opt in sel["options"] if opt.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["value"] == "josh"


def test_voice_select_skips_entries_without_id():
    voices = [{"id": "amy", "label": "Amy"}, {"label": "No ID"}]
    sel = build_voice_select("job-7", voices)
    assert len(sel["options"]) == 1
    assert sel["options"][0]["value"] == "amy"


def test_voice_select_caps_at_25():
    voices = [{"id": f"v{i}", "label": f"Voice {i}"} for i in range(30)]
    sel = build_voice_select("job-8", voices)
    assert len(sel["options"]) <= 25


# ---------------------------------------------------------------------------
# custom_id round-trips
# ---------------------------------------------------------------------------

def test_generate_custom_id_roundtrip():
    cid = f"{GENERATE_PREFIX}abc-123"
    assert is_vid_generate(cid)
    assert job_from_generate(cid) == "abc-123"


def test_generate_id_is_not_refine():
    cid = f"{GENERATE_PREFIX}abc-123"
    assert not is_vid_refine(cid)
    assert not is_vid_refine_modal(cid)


def test_style_custom_id_roundtrip():
    cid = f"{STYLE_PREFIX}job-x"
    assert is_vid_style(cid)
    assert job_from_style(cid) == "job-x"


def test_voice_custom_id_roundtrip():
    cid = f"{VOICE_PREFIX}job-y"
    assert is_vid_voice(cid)
    assert job_from_voice(cid) == "job-y"


def test_refine_custom_id_roundtrip():
    cid = f"{REFINE_PREFIX}job-r"
    assert is_vid_refine(cid)
    assert job_from_refine(cid) == "job-r"


def test_refine_modal_custom_id_roundtrip():
    cid = f"{REFINE_MODAL_PREFIX}job-rm"
    assert is_vid_refine_modal(cid)
    assert job_from_refine_modal(cid) == "job-rm"


def test_apply_custom_id_roundtrip():
    cid = f"{APPLY_PREFIX}job-a"
    assert is_vid_apply(cid)
    assert job_from_apply(cid) == "job-a"


def test_version_custom_id_roundtrip():
    cid = f"{VERSION_PREFIX}job-v"
    assert is_vid_version(cid)
    assert job_from_version(cid) == "job-v"


# ---------------------------------------------------------------------------
# Bare-prefix raises ValueError
# ---------------------------------------------------------------------------

def test_job_from_generate_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_generate(GENERATE_PREFIX)


def test_job_from_style_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_style(STYLE_PREFIX)


def test_job_from_voice_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_voice(VOICE_PREFIX)


def test_job_from_refine_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_refine(REFINE_PREFIX)


def test_job_from_refine_modal_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_refine_modal(REFINE_MODAL_PREFIX)


def test_job_from_apply_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_apply(APPLY_PREFIX)


def test_job_from_version_bare_prefix_raises():
    with pytest.raises(ValueError):
        job_from_version(VERSION_PREFIX)


# ---------------------------------------------------------------------------
# CRITICAL: refine vs refine_modal are disjoint prefixes
# ---------------------------------------------------------------------------

def test_refinemodal_id_does_not_match_refine_predicate():
    """aiuivid:refinemodal:<job> must NOT match is_vid_refine (starts with "aiuivid:refine:")
    because after "aiuivid:refine" comes "modal", not ":". Confirm disjoint routing."""
    cid = "aiuivid:refinemodal:j1"
    assert is_vid_refine(cid) is False
    assert is_vid_refine_modal(cid) is True


def test_refine_id_does_not_match_refine_modal_predicate():
    cid = f"{REFINE_PREFIX}j2"
    assert is_vid_refine(cid) is True
    assert is_vid_refine_modal(cid) is False


# ---------------------------------------------------------------------------
# build_done_components — version select only when versions given
# ---------------------------------------------------------------------------

def test_done_components_with_versions_has_version_select():
    versions = [
        {"version_no": 1, "current": False},
        {"version_no": 2, "current": True},
    ]
    rows = build_done_components("job-d1", versions)
    # First row is Refine button
    assert any(
        c.get("custom_id") == f"{REFINE_PREFIX}job-d1"
        for row in rows for c in row["components"]
    )
    # Second row is a SELECT_MENU for version history
    selects = [c for row in rows for c in row["components"] if c.get("type") == SELECT_MENU]
    assert len(selects) == 1
    assert selects[0]["custom_id"] == f"{VERSION_PREFIX}job-d1"
    labels = [opt["label"] for opt in selects[0]["options"]]
    assert any("current" in lbl for lbl in labels)


def test_done_components_without_versions_has_no_select():
    rows = build_done_components("job-d2", [])
    selects = [c for row in rows for c in row["components"] if c.get("type") == SELECT_MENU]
    assert selects == []


def test_done_components_skips_versions_without_version_no():
    versions = [{"current": True}]  # missing version_no
    rows = build_done_components("job-d3", versions)
    selects = [c for row in rows for c in row["components"] if c.get("type") == SELECT_MENU]
    assert selects == []


# ---------------------------------------------------------------------------
# Refine modal
# ---------------------------------------------------------------------------

def test_refine_modal_custom_id_and_field():
    modal = build_refine_modal("job-rm2")
    assert modal["custom_id"] == f"{REFINE_MODAL_PREFIX}job-rm2"
    inputs = [c for row in modal["components"] for c in row["components"]
              if c.get("type") == TEXT_INPUT]
    assert len(inputs) == 1
    assert inputs[0]["custom_id"] == REFINE_INPUT
    assert inputs[0]["required"] is True


# ---------------------------------------------------------------------------
# build_proposal_components
# ---------------------------------------------------------------------------

def test_proposal_components_has_apply_button():
    rows = build_proposal_components("job-p1")
    buttons = [c for row in rows for c in row["components"] if c.get("type") == BUTTON]
    assert len(buttons) == 1
    assert buttons[0]["custom_id"] == f"{APPLY_PREFIX}job-p1"


def test_mode_select_options_and_predicates():
    from handlers import video_panel as vp
    sel = vp.build_mode_select("j1")
    vals = {o["value"] for o in sel["options"]}
    assert vals == {"remotion", "animated", "slideshow"}
    defaults = [o["value"] for o in sel["options"] if o.get("default")]
    assert defaults == ["remotion"]
    assert vp.is_vid_mode("aiuivid:mode:j1") and vp.job_from_mode("aiuivid:mode:j1") == "j1"


def test_animation_select_options_and_predicates():
    from handlers import video_panel as vp
    sel = vp.build_animation_select("j1")
    vals = {o["value"] for o in sel["options"]}
    assert vals == {"cursor_click", "smooth_scroll", "spotlight", "zoom_pan"}
    defaults = [o["value"] for o in sel["options"] if o.get("default")]
    assert defaults == ["cursor_click"]
    assert vp.is_vid_animation("aiuivid:animation:j1")
    assert vp.job_from_animation("aiuivid:animation:j1") == "j1"


def test_capture_modal_has_url_input():
    from handlers import video_panel as vp
    modal = vp.build_capture_modal("job1")
    assert modal["custom_id"] == "aiuivid:capturemodal:job1"
    inp = modal["components"][0]["components"][0]
    assert inp["custom_id"] == "url"
    assert inp["required"] is True


def test_capture_predicates_and_extractors():
    from handlers import video_panel as vp
    assert vp.is_vid_capture("aiuivid:capture:abc")
    assert vp.is_vid_capture_modal("aiuivid:capturemodal:abc")
    assert not vp.is_vid_capture("aiuivid:capturemodal:abc")  # prefix disjoint
    assert vp.job_from_capture("aiuivid:capture:abc") == "abc"
    assert vp.job_from_capture_modal("aiuivid:capturemodal:abc") == "abc"


# ---------------------------------------------------------------------------
# build_video_embed
# ---------------------------------------------------------------------------

def test_video_embed_has_expected_keys():
    embed = build_video_embed()
    assert "title" in embed
    assert "color" in embed
    assert "description" in embed
    assert "footer" in embed


def test_video_embed_mentions_adding_screenshots():
    embed = build_video_embed()
    desc = embed["description"].lower()
    assert "screenshot" in desc and ("drag" in desc or "paste" in desc)


def test_video_embed_is_slash_free_and_mentions_screenshots():
    embed = build_video_embed()
    assert "/video" not in embed["description"]
    assert "screenshot" in embed["description"].lower()


# ---------------------------------------------------------------------------
# Wizard step builders (W1)
# ---------------------------------------------------------------------------

def test_build_source_components_two_buttons():
    rows = vp.build_source_components("job1")
    assert len(rows) == 1
    btns = rows[0]["components"]
    assert [b["custom_id"] for b in btns] == ["aiuivid:srcurl:job1", "aiuivid:srcshots:job1"]

def test_build_upload_components_continue_button():
    rows = vp.build_upload_components("job1")
    ids = [c["custom_id"] for r in rows for c in r["components"]]
    assert ids == ["aiuivid:srcshotsgo:job1"]

def test_build_describe_components_add_description():
    rows = vp.build_describe_components("job1")
    ids = [c["custom_id"] for r in rows for c in r["components"]]
    assert ids == ["aiuivid:details:job1"]

def test_build_generate_step_components_generate_and_options():
    rows = vp.build_generate_step_components("job1")
    ids = [c["custom_id"] for r in rows for c in r["components"]]
    assert ids == ["aiuivid:generate:job1", "aiuivid:options:job1"]

def test_build_options_components_three_selects_plus_buttons():
    voices = [{"id": "amy", "label": "Amy", "accent": "US", "gender": "Female"}]
    rows = vp.build_options_components("job1", voices)
    # 4 selects + 1 button row (generate + back)
    assert len(rows) == 5
    last_ids = [c["custom_id"] for c in rows[-1]["components"]]
    assert last_ids == ["aiuivid:generate:job1", "aiuivid:optionsback:job1"]
    select_ids = [rows[i]["components"][0]["custom_id"] for i in range(4)]
    assert select_ids == [
        "aiuivid:style:job1",
        "aiuivid:voice:job1",
        "aiuivid:mode:job1",
        "aiuivid:animation:job1",
    ]

def test_new_predicates_round_trip():
    assert vp.is_vid_src_url("aiuivid:srcurl:j") and vp.job_from_src_url("aiuivid:srcurl:j") == "j"
    assert vp.is_vid_src_shots("aiuivid:srcshots:j") and vp.job_from_src_shots("aiuivid:srcshots:j") == "j"
    assert vp.is_vid_src_shots_continue("aiuivid:srcshotsgo:j")
    assert vp.is_vid_options("aiuivid:options:j") and vp.job_from_options("aiuivid:options:j") == "j"
    assert vp.is_vid_options_back("aiuivid:optionsback:j")

def test_new_prefixes_disjoint():
    # trailing-colon safety: srcshots must NOT match srcshotsgo, options must NOT match optionsback
    assert vp.is_vid_src_shots("aiuivid:srcshotsgo:x") is False
    assert vp.is_vid_options("aiuivid:optionsback:x") is False


# ---------------------------------------------------------------------------
# DC1: Choice-card builder + gennow id
# ---------------------------------------------------------------------------

def test_build_choice_components_two_buttons():
    rows = vp.build_choice_components("job1")
    ids = [c["custom_id"] for r in rows for c in r["components"]]
    assert ids == ["aiuivid:gennow:job1", "aiuivid:details:job1"]


def test_gennow_predicate_round_trips():
    assert vp.is_vid_gennow("aiuivid:gennow:j") and vp.job_from_gennow("aiuivid:gennow:j") == "j"


def test_gennow_disjoint_from_generate_and_details():
    assert vp.is_vid_gennow("aiuivid:generate:x") is False
    assert vp.is_vid_gennow("aiuivid:details:x") is False
    assert vp.is_vid_generate("aiuivid:gennow:x") is False
    assert vp.is_vid_details("aiuivid:gennow:x") is False
