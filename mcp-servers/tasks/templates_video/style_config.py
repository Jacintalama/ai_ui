"""Rich visual styles for the pro video render.

This module ADDS a richer style system alongside the existing
:class:`CaptionStyle` / :func:`get_style` / ``STYLES`` machinery (which other
code still uses). A :class:`StyleConfig` embeds a :class:`CaptionStyle` for the
caption look and adds transition/motion/grade/letterbox/card/music fields that
describe a whole visual treatment for a render.

Three styles are registered:

* ``cinematic``: graded, letterboxed, eased motion, ambient bed.
* ``snappy_social``: punchy grade, bold large captions, minimal motion.
* ``clean_product_demo``: no grade, blur-fill pillarbox, gentle motion. This
  is the documented fallback for any unknown style id.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import CaptionStyle


@dataclass(frozen=True)
class StyleConfig:
    """Immutable description of one full visual treatment for a render."""

    id: str
    caption: CaptionStyle
    transitions: dict[str, str]
    motion: str  # one of: "eased" | "gentle" | "minimal"
    grade: str  # ffmpeg filter chain, or "" for none
    letterbox: str  # one of: "none" | "blurfill" | "cinema239"
    cards: dict
    music: str
    music_level: float = 0.25


# Shared logical -> xfade name maps. Each contains at least "crossfade".
_CINEMATIC_TRANSITIONS: dict[str, str] = {
    "crossfade": "fade",
    "dissolve": "dissolve",
    "next": "smoothleft",
    "section": "fadeblack",
}
_SOCIAL_TRANSITIONS: dict[str, str] = {
    "crossfade": "fade",
    "dissolve": "dissolve",
    "next": "slideleft",
    "section": "fadewhite",
}
_PRODUCT_TRANSITIONS: dict[str, str] = {
    "crossfade": "fade",
    "dissolve": "dissolve",
    "next": "smoothleft",
    "section": "fadeblack",
}


CINEMATIC = StyleConfig(
    id="cinematic",
    caption=CaptionStyle(
        font_size_ratio=0.046,
        position="bottom",
        band_color=(10, 12, 18),  # near-black glass slab
        band_opacity=0.35,
        fade_duration=0.6,
    ),
    transitions=_CINEMATIC_TRANSITIONS,
    motion="eased",
    grade=(
        "eq=contrast=1.06:saturation=1.12:brightness=0.01,"
        "curves=all='0/0 0.25/0.22 0.75/0.80 1/1',"
        "vignette=angle=PI/5:eval=init,"
        "noise=alls=8:allf=t+u"
    ),
    letterbox="cinema239",
    cards={
        "bg_color": (8, 10, 14),
        "fg_color": (240, 240, 235),
        "accent_color": (198, 160, 92),
        "font": "serif",
        "logo": True,
    },
    music="ambient",
    music_level=0.22,
)


SNAPPY_SOCIAL = StyleConfig(
    id="snappy_social",
    caption=CaptionStyle(
        font_size_ratio=0.072,
        position="center",
        band_color=(0, 0, 0),
        band_opacity=0.0,  # bold outlined text, no band
        fade_duration=0.18,
    ),
    transitions=_SOCIAL_TRANSITIONS,
    motion="minimal",
    grade="eq=contrast=1.05:saturation=1.3",
    letterbox="none",
    cards={
        "bg_color": (250, 36, 96),
        "fg_color": (255, 255, 255),
        "accent_color": (255, 214, 10),
        "font": "sans-bold",
        "logo": True,
    },
    music="energetic",
    music_level=0.30,
)


CLEAN_PRODUCT_DEMO = StyleConfig(
    id="clean_product_demo",
    caption=CaptionStyle(
        font_size_ratio=0.048,
        position="bottom",
        band_color=(17, 24, 39),  # rounded slate band
        band_opacity=0.62,
        fade_duration=0.4,
    ),
    transitions=_PRODUCT_TRANSITIONS,
    motion="gentle",
    grade="",  # product demo stays true to the captured colors
    letterbox="blurfill",
    cards={
        "bg_color": (248, 250, 252),
        "fg_color": (15, 23, 42),
        "accent_color": (37, 99, 235),
        "font": "sans",
        "logo": True,
    },
    music="neutral",
    music_level=0.18,
)


STYLE_CONFIGS: dict[str, StyleConfig] = {
    CINEMATIC.id: CINEMATIC,
    SNAPPY_SOCIAL.id: SNAPPY_SOCIAL,
    CLEAN_PRODUCT_DEMO.id: CLEAN_PRODUCT_DEMO,
}

# Documented fallback target for unknown style ids.
DEFAULT_STYLE = "clean_product_demo"


def get_style_config(style_id: str | None) -> StyleConfig:
    """Return the :class:`StyleConfig` for ``style_id``.

    Falls back to ``clean_product_demo`` for any unknown or empty id, so a
    stray/legacy id can never break a render.
    """
    return STYLE_CONFIGS.get(style_id or "", STYLE_CONFIGS[DEFAULT_STYLE])


__all__ = ["StyleConfig", "STYLE_CONFIGS", "DEFAULT_STYLE", "get_style_config"]
