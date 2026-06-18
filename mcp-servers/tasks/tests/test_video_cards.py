"""Intro/outro card renderers (Pillow). Fully offline, no ffmpeg.

The cards draw all text with Pillow (never ffmpeg ``drawtext``), so any
characters in a user-supplied title are safe.
"""
from PIL import Image

from video_cards import (
    OUTRO_CTA,
    render_cards,
    render_outro_card_png,
    render_title_card_png,
)

CARDS = {
    "bg_color": (15, 23, 42),
    "fg_color": (240, 244, 255),
    "accent_color": (37, 99, 235),
    "font": "sans",
    "logo": True,
}
SIZE = (1280, 720)


def test_title_card_is_valid_png(tmp_path):
    out = tmp_path / "intro.png"
    path = render_title_card_png("My Cool App", SIZE, CARDS, str(out))
    assert path == str(out)
    img = Image.open(out)
    assert img.size == SIZE
    assert img.mode == "RGB"


def test_outro_card_is_valid_png(tmp_path):
    out = tmp_path / "outro.png"
    render_outro_card_png(OUTRO_CTA, SIZE, CARDS, str(out))
    img = Image.open(out)
    assert img.size == SIZE


def test_card_text_is_injection_safe(tmp_path):
    # Characters that break ffmpeg drawtext / a shell must NOT break Pillow.
    nasty = "a:'\"\\b /etc; rm -rf $(whoami)"
    out = tmp_path / "intro.png"
    render_title_card_png(nasty, SIZE, CARDS, str(out))  # must not raise
    assert Image.open(out).size == SIZE


def test_blank_title_falls_back_without_error(tmp_path):
    out = tmp_path / "intro.png"
    render_title_card_png("   ", SIZE, CARDS, str(out))
    assert Image.open(out).size == SIZE


def test_render_cards_writes_both_into_workdir(tmp_path):
    plan = {
        "title": "Demo",
        "style": "clean_product_demo",
        "scenes": [{"screenshot": "a.png", "duration_s": 3.0}],
    }
    render_cards(plan, str(tmp_path), SIZE)
    assert (tmp_path / "intro.png").exists()
    assert (tmp_path / "outro.png").exists()
    assert Image.open(tmp_path / "intro.png").size == SIZE
    assert Image.open(tmp_path / "outro.png").size == SIZE


def test_render_cards_unknown_style_falls_back(tmp_path):
    # An unknown style must resolve to the default config, not crash.
    plan = {"title": "X", "style": "nope", "scenes": []}
    render_cards(plan, str(tmp_path), SIZE)
    assert (tmp_path / "intro.png").exists()
    assert (tmp_path / "outro.png").exists()
