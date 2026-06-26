from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "static" / "video.html").read_text(
    encoding="utf-8"
)


def test_video_form_has_no_animation_preset_picker():
    # The confusing Animation picker was removed; the smart cursor is automatic.
    assert 'id="animation-preset"' not in HTML
    assert "animation_preset" not in HTML
    assert "_animationPreset" not in HTML


def test_video_form_defaults_to_remotion_animation():
    assert 'id="anim-toggle" checked' in HTML
    assert 'return (!t || t.checked) ? "remotion" : "slideshow";' in HTML
