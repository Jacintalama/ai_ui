"""Tests for video_vision.build_vision_content (pure, no network)."""
import base64
import io
import os

from PIL import Image

from video_vision import build_vision_content, MAX_VISION_IMAGES, VISION_MAX_EDGE


def _make_png(path, w, h):
    Image.new("RGB", (w, h), "white").save(path, "PNG")


def test_builds_leading_text_then_image_and_label(tmp_path):
    p = tmp_path / "shot-1.png"
    _make_png(p, 800, 600)
    parts = build_vision_content([("shot-1.png", str(p))], {"title": "Acme"}, "Make it punchy")
    assert parts[0]["type"] == "text"
    assert "Make it punchy" in parts[0]["text"] and "Acme" in parts[0]["text"]
    assert parts[1]["type"] == "image"
    assert parts[1]["source"]["type"] == "base64"
    assert parts[1]["source"]["media_type"] == "image/jpeg"
    assert parts[2]["type"] == "text" and parts[2]["text"].startswith("shot-1.png")


def test_downscales_large_image(tmp_path):
    p = tmp_path / "big.png"
    _make_png(p, 4000, 3000)
    parts = build_vision_content([("big.png", str(p))], {}, "b")
    img_block = next(b for b in parts if b["type"] == "image")
    raw = base64.standard_b64decode(img_block["source"]["data"])
    with Image.open(io.BytesIO(raw)) as im:
        assert max(im.size) <= VISION_MAX_EDGE


def test_caps_at_max_images(tmp_path):
    imgs = []
    for i in range(MAX_VISION_IMAGES + 4):
        p = tmp_path / f"s{i}.png"
        _make_png(p, 400, 300)
        imgs.append((f"s{i}.png", str(p)))
    parts = build_vision_content(imgs, {}, "b")
    assert sum(1 for b in parts if b["type"] == "image") == MAX_VISION_IMAGES


def test_skips_unreadable_image(tmp_path):
    good = tmp_path / "good.png"
    _make_png(good, 400, 300)
    parts = build_vision_content(
        [("missing.png", str(tmp_path / "missing.png")), ("good.png", str(good))],
        {}, "b")
    images = [b for b in parts if b["type"] == "image"]
    labels = [b["text"] for b in parts if b["type"] == "text" and b["text"].startswith(("good", "missing"))]
    assert len(images) == 1
    assert any(l.startswith("good.png") for l in labels)
