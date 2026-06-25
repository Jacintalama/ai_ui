"""Turn captured screenshots + page context into multimodal content blocks for
the planner's vision call. Pure (no network). The downscaled JPEGs here are ONLY
for the model to understand the page; the final render uses the full-res PNGs.
"""
from __future__ import annotations

import base64
import io
import logging

from PIL import Image

logger = logging.getLogger("video_vision")

MAX_VISION_IMAGES = 8
VISION_MAX_EDGE = 1568  # long-edge cap: ~1.6k image tokens each (vs ~4.8k full-res)


def _downscale_jpeg_b64(path: str) -> str | None:
    """Open, downscale to <= VISION_MAX_EDGE on the long edge, re-encode JPEG,
    base64. Returns None (skip) on any failure. Pillow's default MAX_IMAGE_PIXELS
    decompression-bomb guard is left ON so an oversize upload is skipped here."""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, VISION_MAX_EDGE / max(w, h))
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:  # noqa: BLE001 - corrupt/oversize/missing -> skip, never raise
        logger.warning("vision downscale skipped %s: %s", path, e)
        return None


def _context_text(site_context: dict) -> str:
    ctx = site_context or {}
    title = (ctx.get("title") or "").strip()
    headings = "; ".join(ctx.get("headings") or [])
    meta = (ctx.get("meta_description") or "").strip()
    bits = []
    if title:
        bits.append(f"Page title: {title}")
    if headings:
        bits.append(f"Key text on the pages: {headings}")
    if meta:
        bits.append(f"Description: {meta}")
    return "\n".join(bits)


def build_vision_content(images, site_context, brief) -> list[dict]:
    """images: ordered list of (basename, abs_path). Returns a user-content list:
    a leading text block (brief + page context), then per image an image block
    followed by a small text label naming the exact basename (so the model can
    reference it in scene['screenshot']). Caps at MAX_VISION_IMAGES; skips
    unreadable files."""
    header = (brief or "").strip()
    ctx = _context_text(site_context)
    if ctx:
        header = (header + "\n\n" + ctx).strip()
    parts: list[dict] = [{"type": "text",
                          "text": header or "Make a strong short product video from these pages."}]
    page = 0
    for basename, path in list(images)[:MAX_VISION_IMAGES]:
        b64 = _downscale_jpeg_b64(path)
        if b64 is None:
            continue
        page += 1
        parts.append({"type": "image",
                      "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        parts.append({"type": "text", "text": f"{basename} (page {page})"})
    return parts
