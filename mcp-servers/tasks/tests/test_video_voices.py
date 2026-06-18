"""Unit tests for the curated voice library (video_voices). Fully offline."""
import os

from video_voices import (
    DEFAULT_VOICE_ID,
    VOICES,
    is_valid_voice,
    resolve_model,
    voice_catalog,
)

EXPECTED_IDS = ["amy", "ryan", "lessac", "joe", "alan", "alba"]


def test_default_voice_is_amy_and_first():
    assert DEFAULT_VOICE_ID == "amy"
    assert VOICES[0].id == "amy"


def test_resolve_model_known():
    assert resolve_model("alan").endswith("en_GB-alan-medium.onnx")
    assert resolve_model("ryan").endswith("en_US-ryan-high.onnx")


def test_resolve_model_unknown_and_none_fall_back_to_default():
    default_model = resolve_model("amy")
    assert resolve_model("not-a-voice") == default_model
    assert resolve_model(None) == default_model
    assert resolve_model("") == default_model


def test_is_valid_voice():
    assert is_valid_voice("ryan")
    assert not is_valid_voice("not-a-voice")
    assert not is_valid_voice(None)
    assert not is_valid_voice("")


def test_catalog_ids_order_and_single_default():
    cat = voice_catalog()
    assert [c["id"] for c in cat] == EXPECTED_IDS
    assert sum(1 for c in cat if c["default"]) == 1
    assert next(c for c in cat if c["default"])["id"] == "amy"


def test_catalog_exposes_sample_url_not_server_paths():
    for c in voice_catalog():
        assert c["sample_url"] == "/tasks/static/voices/%s.mp3" % c["id"]
        # The picker payload must never leak the host model path.
        assert "model" not in c
        assert "/opt/piper" not in str(c)


def test_all_models_under_voices_dir():
    for v in VOICES:
        assert v.model.startswith("/opt/piper/voices/")
        assert v.model.endswith(".onnx")


def test_preview_clip_committed_for_every_voice():
    # A committed static/voices/<id>.mp3 must back every catalog voice so the
    # picker's preview never 404s. Guards drift between the allowlist + clips.
    static_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "voices"
    )
    for c in voice_catalog():
        clip = os.path.join(static_dir, c["id"] + ".mp3")
        assert os.path.exists(clip), "missing preview clip: " + clip
        assert os.path.getsize(clip) > 1000, "suspiciously tiny clip: " + clip
