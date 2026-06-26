"""Smart cursor-click: the vision-LLM marks an optional per-scene click target
{x,y (image fractions), label}; the cursor clicks real elements. Schema carries
it, the prompt instruction lives OUTSIDE the editable skill, and a sanitizer
drops invalid/misplaced clicks. (2026-06-26.)
"""
import base64
import json
import os

os.environ.setdefault("AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("DATABASE_URL", "postgresql://t:t@localhost/test")

from video_plan import (  # noqa: E402
    ANIM_BEST_PRACTICES,
    ANIM_PLAN_SCHEMA,
    build_anim_system_prompt,
    sanitize_anim_clicks,
)


# --- schema -------------------------------------------------------------------
def test_scene_has_optional_click_target():
    scene = ANIM_PLAN_SCHEMA["properties"]["scenes"]["items"]
    assert "click" in scene["properties"], "scene schema missing click"
    assert "click" not in scene["required"], "click must be OPTIONAL"
    click = scene["properties"]["click"]
    assert click["type"] == "object"
    assert click["additionalProperties"] is False
    assert set(click["required"]) == {"x", "y", "label"}


def test_click_schema_has_no_unsupported_range_keywords():
    # Anthropic structured outputs reject minimum/maximum (same family as maxItems).
    blob = json.dumps(ANIM_PLAN_SCHEMA)
    assert "minimum" not in blob
    assert "maximum" not in blob


# --- prompt: instruction lives OUTSIDE the editable skill ----------------------
def test_click_instruction_is_in_prompt_even_with_a_custom_skill():
    # A user editing the remotion-best-practices skill must not be able to delete
    # the click feature, so the instruction lives in the fixed wrapper, not the skill.
    sp = build_anim_system_prompt("CUSTOM SKILL TEXT with no mention of clicking.")
    low = sp.lower()
    assert "click" in low
    assert "clickable" in low
    assert "CUSTOM SKILL TEXT" in sp  # the skill is still injected


def test_click_instruction_not_part_of_builtin_best_practices():
    assert "clickable" not in ANIM_BEST_PRACTICES.lower()


# --- sanitizer ----------------------------------------------------------------
def _plan(scenes):
    return {"title": "t", "scenes": scenes, "narration_script": "n"}


def test_sanitize_keeps_valid_click_on_screenshot():
    p = _plan([{"kind": "screenshot", "screenshot": "s1.png", "motion": "zoom-in",
                "duration_s": 3, "click": {"x": 0.5, "y": 0.3, "label": "Contact"}}])
    sanitize_anim_clicks(p)
    assert p["scenes"][0]["click"] == {"x": 0.5, "y": 0.3, "label": "Contact"}


def test_sanitize_drops_out_of_range_click():
    p = _plan([{"kind": "screenshot", "screenshot": "s1.png", "motion": "zoom-in",
                "duration_s": 3, "click": {"x": 1.5, "y": 0.3, "label": "x"}}])
    sanitize_anim_clicks(p)
    assert "click" not in p["scenes"][0]


def test_sanitize_drops_click_on_non_screenshot_scene():
    p = _plan([{"kind": "title", "headline": "Hi", "motion": "rise", "duration_s": 2.5,
                "click": {"x": 0.5, "y": 0.3, "label": "x"}}])
    sanitize_anim_clicks(p)
    assert "click" not in p["scenes"][0]


def test_sanitize_drops_click_missing_coords():
    p = _plan([{"kind": "screenshot", "screenshot": "s1.png", "motion": "zoom-in",
                "duration_s": 3, "click": {"label": "no coords"}}])
    sanitize_anim_clicks(p)
    assert "click" not in p["scenes"][0]


def test_sanitize_truncates_long_label():
    p = _plan([{"kind": "screenshot", "screenshot": "s1.png", "motion": "zoom-in",
                "duration_s": 3, "click": {"x": 0.5, "y": 0.3, "label": "L" * 200}}])
    sanitize_anim_clicks(p)
    assert len(p["scenes"][0]["click"]["label"]) <= 60


# --- renderer plumbing: the worker must forward click (drop-point #1) ----------
def test_remotion_scene_dict_forwards_click():
    from video_remotion_render import remotion_scene_dict

    d = remotion_scene_dict(
        {"kind": "screenshot", "motion": "zoom-in", "duration_s": 3,
         "click": {"x": 0.4, "y": 0.2, "label": "Buy"}},
        "/abs/s1.png",
    )
    assert d["click"] == {"x": 0.4, "y": 0.2, "label": "Buy"}
    assert d["screenshot"] == "/abs/s1.png"
    assert d["durationS"] == 3.0


def test_remotion_scene_dict_omits_absent_click():
    from video_remotion_render import remotion_scene_dict

    d = remotion_scene_dict({"kind": "screenshot", "motion": "fade", "duration_s": 2}, "/abs/s.png")
    assert "click" not in d
