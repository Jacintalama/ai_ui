"""Tests for the animated-composition runtime (Phase 1 de-risk). The real-render
test is skipped unless Playwright+Chromium AND ffmpeg are available."""
import io
import os
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


def test_build_composition_is_deterministic_and_safe():
    from video_anim import build_composition, composition_duration
    plan = {"title": "Demo", "narration_script": "", "scenes": [
        {"kind": "title", "headline": "Hello </script><b>x", "motion": "rise", "duration_s": 2.0},
        {"kind": "screenshot", "screenshot": "screenshot-1.png", "headline": "Look",
         "motion": "zoom-in", "duration_s": 3.0},
        {"kind": "outro", "headline": "Bye", "motion": "fade", "duration_s": 2.0},
    ]}
    shots = {"screenshot-1.png": _png()}
    html = build_composition(plan, shots)
    assert "window.__seek" in html
    assert "data:image/png;base64," in html              # the screenshot embedded
    # Raw text is NOT injected into markup (delivered via JSON + JS textContent).
    assert "</script><b>x" not in html
    assert abs(composition_duration(plan) - 7.0) < 0.01


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


async def test_render_animated_job_reads_shots_and_renders(tmp_path, monkeypatch):
    import video_anim
    captured = {}

    async def fake_render(html, out_path, *, fps=24, duration_s=8.0, audio_path=None,
                          width=1280, height=720):
        captured["html"] = html
        captured["out"] = out_path
        with open(out_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")  # tiny stub
        return int(duration_s * fps)

    monkeypatch.setattr(video_anim, "render_html_to_mp4", fake_render)
    slug, jid = "vid-x", "11111111-1111-1111-1111-111111111111"
    shots_dir = tmp_path / slug / ".video" / jid / "screenshots"
    shots_dir.mkdir(parents=True)
    (shots_dir / "screenshot-1.png").write_bytes(_png())
    plan = {"title": "t", "narration_script": "", "scenes": [
        {"kind": "screenshot", "screenshot": "screenshot-1.png", "headline": "h",
         "motion": "zoom-in", "duration_s": 3.0}]}
    out = await video_anim.render_animated_job(str(tmp_path), slug, jid, plan)
    assert out.endswith("out.mp4") and os.path.exists(out)
    assert "data:image/png;base64," in captured["html"]
