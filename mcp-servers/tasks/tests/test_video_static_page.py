from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "static" / "video.html").read_text(
    encoding="utf-8"
)


def test_video_form_exposes_animation_choices():
    assert 'id="animation-preset"' in HTML
    assert 'name="animation_preset"' in HTML
    for value in ("cursor_click", "smooth_scroll", "spotlight", "zoom_pan"):
        assert f'value="{value}"' in HTML
    assert 'value="cursor_click" selected' in HTML


def test_video_form_submits_animation_preset():
    assert 'const animationPresetSelect = document.getElementById("animation-preset");' in HTML
    assert 'function _animationPreset()' in HTML
    assert 'fd.append("animation_preset", _animationPreset());' in HTML
    assert 'animation_preset: _animationPreset()' in HTML


def test_video_form_defaults_to_remotion_animation():
    assert 'id="anim-toggle" checked' in HTML
    assert 'return (!t || t.checked) ? "remotion" : "slideshow";' in HTML
