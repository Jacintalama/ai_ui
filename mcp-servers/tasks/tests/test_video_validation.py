"""Unit tests for video_validation. Pure functions, no fixtures needed."""
import io

import pytest
from PIL import Image

from video_validation import ScreenshotRejected, validate_screenshot


def _png(w=100, h=100):
    b = io.BytesIO()
    Image.new("RGB", (w, h), "blue").save(b, "PNG")
    return b.getvalue()


def test_accepts_small_png():
    validate_screenshot("a.png", _png())  # no raise


def test_rejects_non_image_bytes():
    with pytest.raises(ScreenshotRejected):
        validate_screenshot("a.png", b"not an image")


def test_rejects_oversize_dimensions():
    with pytest.raises(ScreenshotRejected):
        validate_screenshot("a.png", _png(5000, 5000))
