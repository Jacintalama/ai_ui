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


def test_sample_text_matches_generator_script():
    # The committed clips were rendered from SAMPLE_TEXT by gen_voice_previews.sh.
    # If the constant and the script's TXT drift, the previews silently stop
    # matching the documented sample line. Keep them in lockstep.
    import re

    from video_voices import SAMPLE_TEXT

    tasks_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.normpath(
        os.path.join(tasks_dir, "..", "..", "scripts", "gen_voice_previews.sh")
    )
    with open(script, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r'TXT="([^"]*)"', text)
    assert m is not None, "TXT=... not found in gen_voice_previews.sh"
    assert m.group(1) == SAMPLE_TEXT


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


# --- resolve_model_on_disk: never let a chosen voice render silently ----------
# resolve_model() returns the nominal path without checking the file exists, so a
# valid voice whose .onnx was never provisioned (e.g. lessac) yields a silent
# video. resolve_model_on_disk() prefers the requested voice but falls back to the
# default voice when the requested model is missing on the render host.


def test_resolve_model_on_disk_prefers_requested_when_present():
    from video_voices import resolve_model_on_disk

    m = resolve_model_on_disk("lessac", exists=lambda p: True)
    assert m.endswith("en_US-lessac-medium.onnx")


def test_resolve_model_on_disk_falls_back_to_default_when_requested_missing():
    from video_voices import resolve_model_on_disk

    amy = resolve_model("amy")
    # lessac model absent, amy present -> fall back to amy (never silent).
    m = resolve_model_on_disk("lessac", exists=lambda p: p == amy)
    assert m == amy


def test_resolve_model_on_disk_none_when_nothing_installed():
    from video_voices import resolve_model_on_disk

    assert resolve_model_on_disk("lessac", exists=lambda p: False) is None


def test_resolve_model_on_disk_unknown_id_uses_default():
    from video_voices import resolve_model_on_disk

    amy = resolve_model("amy")
    assert resolve_model_on_disk("nope", exists=lambda p: p == amy) == amy


def test_dockerfile_provisions_every_catalog_voice():
    # Every selectable voice's .onnx model MUST be baked into the tasks image,
    # else picking it yields a silent video (the model is absent on the render
    # host). Guards the UI-offers-voice vs not-provisioned drift that made every
    # non-default voice silent.
    tasks_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(tasks_dir, "Dockerfile"), encoding="utf-8") as fh:
        dockerfile = fh.read()
    for v in VOICES:
        stem = os.path.splitext(os.path.basename(v.model))[0]  # e.g. en_US-lessac-medium
        assert stem in dockerfile, f"Dockerfile does not provision voice model {stem}"
