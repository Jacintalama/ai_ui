"""Video caption-style templates.

Each template module exposes a plain ``STYLE`` dict of *style only* parameters.
This package wraps them into an immutable :class:`CaptionStyle` and offers
:func:`get_style`, which falls back to the ``product_demo`` style for any
unknown ``template_id`` (so a stray/legacy id can never break a render).
"""
from __future__ import annotations

from dataclasses import dataclass

from .feature_walkthrough import STYLE as _FEATURE_WALKTHROUGH
from .product_demo import STYLE as _PRODUCT_DEMO


@dataclass(frozen=True)
class CaptionStyle:
    """Immutable caption/transition style for one video template."""

    font_size_ratio: float
    position: str
    band_color: tuple[int, int, int]
    band_opacity: float
    fade_duration: float


STYLES: dict[str, CaptionStyle] = {
    "product_demo": CaptionStyle(**_PRODUCT_DEMO),
    "feature_walkthrough": CaptionStyle(**_FEATURE_WALKTHROUGH),
}

# Documented fallback target for unknown template ids.
DEFAULT_TEMPLATE = "product_demo"


def get_style(template_id: str | None) -> CaptionStyle:
    """Return the style for ``template_id``, falling back to ``product_demo``."""
    return STYLES.get(template_id or "", STYLES[DEFAULT_TEMPLATE])


# Richer visual-style registry layered on top of ``CaptionStyle``. Imported
# after ``CaptionStyle`` is defined above so ``style_config``'s
# ``from . import CaptionStyle`` resolves without a circular-import error.
from .style_config import (  # noqa: E402
    StyleConfig,
    STYLE_CONFIGS,
    get_style_config,
)

__all__ = [
    "CaptionStyle",
    "STYLES",
    "DEFAULT_TEMPLATE",
    "get_style",
    "StyleConfig",
    "STYLE_CONFIGS",
    "get_style_config",
]
