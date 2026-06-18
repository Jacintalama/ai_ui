"""Unit tests for video_plan.validate_plan. Pure functions, run fully offline.

Also includes one mocked generate_plan test that monkeypatches the anthropic
client so it never hits the network.
"""
import json

import anthropic
import pytest

from video_plan import PlanInvalid, generate_plan, validate_plan


def test_rejects_unknown_template():
    with pytest.raises(PlanInvalid):
        validate_plan(
            {"template_id": "nope", "title": "t", "scenes": [], "narration_script": "x"},
            available=["screenshot-1.png"],
        )


def test_rejects_missing_screenshot():
    p = {
        "template_id": "product_demo",
        "title": "t",
        "scenes": [
            {
                "screenshot": "screenshot-9.png",
                "caption": "c",
                "duration_s": 3.0,
                "transition": "crossfade",
            }
        ],
        "narration_script": "hi",
    }
    with pytest.raises(PlanInvalid):
        validate_plan(p, available=["screenshot-1.png"])


def test_accepts_valid_plan():
    p = {
        "template_id": "product_demo",
        "title": "t",
        "scenes": [
            {
                "screenshot": "screenshot-1.png",
                "caption": "c",
                "duration_s": 3.0,
                "transition": "crossfade",
            }
        ],
        "narration_script": "hi",
        "resolution": "720p",
    }
    validate_plan(p, available=["screenshot-1.png"])  # no raise


class _Block:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Msg:
    def __init__(self, content):
        self.content = content


class _Messages:
    def __init__(self, payload: str):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg([_Block(self._payload)])


class _FakeClient:
    def __init__(self, payload: str):
        self.messages = _Messages(payload)


async def test_generate_plan_parses_and_validates(monkeypatch):
    canned = {
        "template_id": "product_demo",
        "title": "Demo",
        "scenes": [
            {
                "screenshot": "screenshot-1.png",
                "caption": "c",
                "duration_s": 4.0,
                "transition": "cut",
            }
        ],
        "narration_script": "hi",
    }
    fake = _FakeClient(json.dumps(canned))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: fake)

    result = await generate_plan("make a demo", ["screenshot-1.png"])

    # clamp_plan normalizes the resolution to the box-safe 720p.
    assert result == {**canned, "resolution": "720p"}
    # Confirm the call uses the current model id and structured-output API.
    sent = fake.messages.calls[0]
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_config"]["format"]["type"] == "json_schema"


def test_clamp_plan_clamps_per_scene_duration():
    from video_plan import clamp_plan
    p = {"template_id": "product_demo", "title": "t",
         "scenes": [{"screenshot": "a.png", "caption": "c", "duration_s": 25, "transition": "cut"},
                    {"screenshot": "b.png", "caption": "c", "duration_s": 0.1, "transition": "cut"}],
         "narration_script": "n"}
    out = clamp_plan(p)
    assert out["scenes"][0]["duration_s"] == 15      # clamped down from 25
    assert out["scenes"][1]["duration_s"] == 0.5     # clamped up from 0.1


def test_clamp_plan_caps_resolution_to_720p():
    from video_plan import PLAN_SCHEMA, clamp_plan
    # 1080p OOMs the render box, so it must never reach the renderer.
    p = {"template_id": "product_demo", "title": "t", "resolution": "1080p",
         "scenes": [{"screenshot": "a.png", "caption": "c", "duration_s": 3,
                     "transition": "cut"}],
         "narration_script": "n"}
    assert clamp_plan(p)["resolution"] == "720p"
    # A plan with no resolution is normalized to 720p too.
    p2 = dict(p); p2.pop("resolution")
    assert clamp_plan(p2)["resolution"] == "720p"
    # The model can only emit 720p (schema enum narrowed).
    assert PLAN_SCHEMA["properties"]["resolution"]["enum"] == ["720p"]


def test_clamp_plan_scales_total_over_cap():
    from video_plan import clamp_plan
    scenes = [{"screenshot": f"{i}.png", "caption": "c", "duration_s": 15, "transition": "cut"} for i in range(6)]
    out = clamp_plan({"template_id": "product_demo", "title": "t", "scenes": scenes, "narration_script": "n"})
    assert sum(s["duration_s"] for s in out["scenes"]) <= 60 + 0.01


def test_clamp_plan_lets_overlong_single_scene_pass_validation():
    from video_plan import clamp_plan
    p = {"template_id": "product_demo", "title": "t",
         "scenes": [{"screenshot": "shot.png", "caption": "c", "duration_s": 30, "transition": "cut"}],
         "narration_script": "n"}
    validate_plan(clamp_plan(p), ["shot.png"])  # must not raise


def test_scene_schema_has_narration_property():
    from video_plan import PLAN_SCHEMA
    scene_props = PLAN_SCHEMA["properties"]["scenes"]["items"]["properties"]
    assert scene_props["narration"] == {"type": "string"}
    # Back-compat: per-scene narration is optional, never required.
    required = PLAN_SCHEMA["properties"]["scenes"]["items"].get("required", [])
    assert "narration" not in required


def test_scene_transition_enum_widened():
    from video_plan import PLAN_SCHEMA
    enum = PLAN_SCHEMA["properties"]["scenes"]["items"]["properties"]["transition"]["enum"]
    assert set(enum) == {"cut", "crossfade", "dissolve", "next", "section"}


def test_validate_plan_accepts_scene_narration():
    p = {
        "template_id": "product_demo",
        "title": "t",
        "scenes": [
            {
                "screenshot": "screenshot-1.png",
                "caption": "c",
                "duration_s": 3.0,
                "transition": "dissolve",
                "narration": "spoken line for this scene",
            }
        ],
        "narration_script": "hi",
    }
    validate_plan(p, available=["screenshot-1.png"])  # must not raise


def test_clamp_plan_trim_loop_keeps_floor():
    from video_plan import clamp_plan
    # Feasible mixed plan: 4x15s + 40x0.5s = 80s total, every scene individually
    # valid. Proportional scaling floor-bumps the tiny scenes, pushing the total
    # back over the cap, so the trim loop must shave the longest scenes down.
    scenes = [
        {"screenshot": f"big-{i}.png", "caption": "c", "duration_s": 15, "transition": "cut"}
        for i in range(4)
    ] + [
        {"screenshot": f"small-{i}.png", "caption": "c", "duration_s": 0.5, "transition": "cut"}
        for i in range(40)
    ]
    out = clamp_plan(
        {"template_id": "product_demo", "title": "t", "scenes": scenes, "narration_script": "n"}
    )
    assert sum(s["duration_s"] for s in out["scenes"]) <= 60
    assert min(s["duration_s"] for s in out["scenes"]) >= 0.5


def test_clamp_plan_floor_bumped_total_capped():
    from video_plan import MAX_TOTAL_SECONDS, clamp_plan
    scenes = [
        {"screenshot": f"{i}.png", "caption": "c", "duration_s": 0.1, "transition": "cut"}
        for i in range(200)
    ]
    out = clamp_plan(
        {"template_id": "product_demo", "title": "t", "scenes": scenes, "narration_script": "n"}
    )
    assert sum(s["duration_s"] for s in out["scenes"]) <= MAX_TOTAL_SECONDS
