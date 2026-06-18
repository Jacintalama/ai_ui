"""Intro title card + outro CTA card renderers for the pro video render.

Both cards are rendered with Pillow to opaque PNGs that ffmpeg later overlays
on a solid ``lavfi`` color canvas (see ``video_render.build_render_script``).
User-supplied text (the video title) is drawn by Pillow, never passed to
ffmpeg ``drawtext``, so it cannot break the filter parser or the shell.

This module depends on ``video_render`` for the shared text helpers and the
card file-path contract. ``video_render`` must NOT import this module, so the
import graph stays acyclic: ``video_executor`` imports both, and this module
imports ``video_render``.
"""
from __future__ import annotations

import os
from typing import Sequence

from PIL import Image, ImageDraw

from templates_video import get_style_config
from video_render import (
    DEFAULT_FONT_PATH,
    _intro_card_path,
    _line_height,
    _load_font,
    _outro_card_path,
    _text_width,
    _wrap_text,
)

# The bundled brand logo, if present on the render host. Optional: when the
# asset is absent (e.g. in tests) the card renders without it.
LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.png")

# Default intro title when a plan carries none.
DEFAULT_TITLE = "AIUI"
# Outro call to action: the public site. A constant, never user input.
OUTRO_CTA = "ai-ui.coolestdomain.win"
# Small eyebrow label above the outro URL.
OUTRO_EYEBROW = "Build it yourself at"


def _rgb(value: Sequence[int]) -> tuple[int, int, int]:
    r, g, b = (max(0, min(255, int(c))) for c in value)
    return (r, g, b)


def _maybe_paste_logo(img: Image.Image, top: int) -> None:
    """Paste the bundled logo centered near the top, if the asset exists."""
    if not os.path.exists(LOGO_PATH):
        return
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except OSError:
        return
    target_h = max(24, img.height // 12)
    ratio = target_h / logo.height
    target_w = max(1, int(round(logo.width * ratio)))
    logo = logo.resize((target_w, target_h))
    x = (img.width - target_w) // 2
    img.paste(logo, (x, top), logo)


def _render_card(
    size: tuple[int, int],
    cards: dict,
    out_path: str,
    *,
    primary: str,
    eyebrow: str | None = None,
    font_path: str = DEFAULT_FONT_PATH,
) -> str:
    """Render a centered title/CTA card to ``out_path`` (opaque PNG).

    ``primary`` is the large headline (wrapped to fit); ``eyebrow`` is an
    optional small accent-colored label above it. An accent bar is drawn under
    the headline. All text is drawn by Pillow, so any characters are safe.
    """
    width, height = int(size[0]), int(size[1])
    bg = _rgb(cards.get("bg_color", (10, 12, 16)))
    fg = _rgb(cards.get("fg_color", (240, 240, 240)))
    accent = _rgb(cards.get("accent_color", (99, 102, 241)))

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    margin = max(8, int(width * 0.08))
    max_text_width = max(1, width - 2 * margin)

    primary_px = max(24, height // 8)
    primary_font = _load_font(font_path, primary_px)
    primary_lines = _wrap_text(draw, primary, primary_font, max_text_width)
    primary_lh = _line_height(draw, primary_font)

    eyebrow_lines: list[str] = []
    eyebrow_font = None
    eyebrow_lh = 0
    if eyebrow:
        eyebrow_px = max(14, height // 24)
        eyebrow_font = _load_font(font_path, eyebrow_px)
        eyebrow_lines = _wrap_text(draw, eyebrow, eyebrow_font, max_text_width)
        eyebrow_lh = _line_height(draw, eyebrow_font)

    accent_bar_h = max(4, height // 90)
    accent_gap = max(8, primary_lh // 2)
    eyebrow_gap = eyebrow_lh // 2 if eyebrow_lines else 0

    block_h = (
        len(eyebrow_lines) * eyebrow_lh
        + eyebrow_gap
        + len(primary_lines) * primary_lh
        + accent_gap
        + accent_bar_h
    )
    y = max(margin, (height - block_h) // 2)

    _maybe_paste_logo(img, margin)

    if eyebrow_font is not None:
        for line in eyebrow_lines:
            w = _text_width(draw, line, eyebrow_font)
            draw.text(((width - w) / 2, y), line, font=eyebrow_font, fill=accent)
            y += eyebrow_lh
        y += eyebrow_gap

    for line in primary_lines:
        w = _text_width(draw, line, primary_font)
        draw.text(((width - w) / 2, y), line, font=primary_font, fill=fg)
        y += primary_lh

    y += accent_gap
    bar_w = max(40, int(width * 0.16))
    x0 = (width - bar_w) // 2
    draw.rectangle([x0, y, x0 + bar_w, y + accent_bar_h], fill=accent)

    img.save(out_path, "PNG")
    return out_path


def render_title_card_png(
    title: str,
    size: tuple[int, int],
    cards: dict,
    out_path: str,
    *,
    font_path: str = DEFAULT_FONT_PATH,
) -> str:
    """Render the intro title card. Falls back to ``DEFAULT_TITLE`` if blank."""
    headline = (title or "").strip() or DEFAULT_TITLE
    return _render_card(
        size, cards, out_path, primary=headline, font_path=font_path
    )


def render_outro_card_png(
    cta: str,
    size: tuple[int, int],
    cards: dict,
    out_path: str,
    *,
    font_path: str = DEFAULT_FONT_PATH,
) -> str:
    """Render the outro call-to-action card. Falls back to ``OUTRO_CTA``."""
    url = (cta or "").strip() or OUTRO_CTA
    return _render_card(
        size,
        cards,
        out_path,
        primary=url,
        eyebrow=OUTRO_EYEBROW,
        font_path=font_path,
    )


def render_cards(plan: dict, workdir: str, size: tuple[int, int]) -> None:
    """Write the intro + outro card PNGs into ``workdir`` for ``plan``.

    Runs in-container alongside ``render_all_captions`` (Pillow only, no ffmpeg).
    Resolves the visual style from the plan so the card colors/fonts match the
    rest of the render.
    """
    workdir = str(workdir).rstrip("/")
    os.makedirs(workdir, exist_ok=True)
    style = get_style_config(plan.get("style"))
    cards = style.cards
    title = plan.get("title") or DEFAULT_TITLE
    render_title_card_png(title, size, cards, _intro_card_path(workdir))
    render_outro_card_png(OUTRO_CTA, size, cards, _outro_card_path(workdir))
