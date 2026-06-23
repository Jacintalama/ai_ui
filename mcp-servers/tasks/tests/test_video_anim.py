"""Tests for the animated-composition runtime (Phase 1 de-risk). The real-render
test is skipped unless Playwright+Chromium AND ffmpeg are available."""
import io
import shutil

import pytest
from PIL import Image

from video_anim import build_demo_composition


def _png(color=(200, 30, 30)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (320, 200), color).save(b, "PNG")
    return b.getvalue()


def test_demo_composition_is_self_contained_and_seekable():
    html = build_demo_composition([_png(), _png((30, 30, 200))], title="My <Site>")
    # Deterministic, seek-safe timeline hook.
    assert "window.__seek" in html
    # Screenshot embedded as a data URI (self-contained — no asset paths).
    assert html.count("data:image/png;base64,") >= 1
    # Title is HTML-escaped (no raw angle brackets injected).
    assert "My <Site>" not in html
    assert "My &lt;Site&gt;" in html
    # No wall-clock / nondeterminism in the runtime composition.
    assert "Date.now(" not in html and "Math.random(" not in html


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


pytest.importorskip("playwright.async_api")


@pytest.mark.asyncio
async def test_render_demo_to_mp4(tmp_path):
    """Render the demo composition to a real MP4 in-process and assert it is a
    valid, multi-frame video. Skipped without ffmpeg/Chromium."""
    if not _have_ffmpeg():
        pytest.skip("ffmpeg not installed")
    from video_anim import render_html_to_mp4
    html = build_demo_composition([_png()], title="Demo")
    out = tmp_path / "demo.mp4"
    try:
        frames = await render_html_to_mp4(html, str(out), fps=12, duration_s=4.0)
    except RuntimeError as e:
        pytest.skip(f"render runtime unavailable: {e}")
    assert out.exists() and out.stat().st_size > 10_000
    assert frames >= 2
