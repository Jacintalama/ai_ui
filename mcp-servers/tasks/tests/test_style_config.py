"""Offline tests for the StyleConfig registry (pure dataclasses)."""
from templates_video.style_config import get_style_config, STYLE_CONFIGS


def test_three_styles_registered():
    assert set(STYLE_CONFIGS) == {"cinematic", "snappy_social", "clean_product_demo"}


def test_get_style_config_fallback():
    c = get_style_config("nope")            # unknown -> default clean_product_demo
    assert c.id == "clean_product_demo"


def test_style_shapes():
    c = get_style_config("cinematic")
    assert c.grade                          # cinematic has a grade chain (non-empty)
    assert c.letterbox in ("none", "blurfill", "cinema239")
    assert c.motion in ("eased", "gentle", "minimal")
    assert "crossfade" in c.transitions     # transitions maps logical->xfade name
    assert c.music                          # a music track id
    cp = get_style_config("clean_product_demo")
    assert cp.grade == ""                   # product-demo: no grade
