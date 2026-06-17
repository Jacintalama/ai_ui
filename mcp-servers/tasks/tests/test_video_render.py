"""Offline structural tests for video_render.

ffmpeg is not installed locally and the real encode happens on the render host
at deploy time, so these tests verify the *structure* of the produced ffmpeg
argv (not an actual encode). Caption-PNG generation uses Pillow and IS exercised
for real here.
"""
import re

from PIL import Image

from templates_video import get_style
from video_render import (
    RESOLUTIONS,
    build_render_script,
    caption_paths,
    render_caption_png,
)

WORKDIR = "/srv/.video/job-123"


def _plan(**overrides) -> dict:
    plan = {
        "template_id": "product_demo",
        "title": "Demo",
        "scenes": [
            {
                "screenshot": "screenshot-1.png",
                "caption": "First scene caption that is long enough to wrap",
                "duration_s": 3.0,
                "transition": "crossfade",
            },
            {
                "screenshot": "screenshot-2.png",
                "caption": "Second scene",
                "duration_s": 2.5,
                "transition": "cut",
            },
            {
                "screenshot": "screenshot-3.png",
                "caption": "Third and final scene",
                "duration_s": 2.0,
                "transition": "crossfade",
            },
        ],
        "narration_script": "hello there",
        "resolution": "720p",
    }
    plan.update(overrides)
    return plan


def test_resolution_maps_720p():
    argv = build_render_script(_plan(), WORKDIR)
    joined = " ".join(argv)
    assert RESOLUTIONS["720p"] == (1280, 720)
    assert ("1280:720" in joined) or ("1280x720" in joined)
    assert any(arg.endswith("out.mp4") for arg in argv)


def test_argv_references_every_screenshot_and_voice():
    plan = _plan()
    argv = build_render_script(plan, WORKDIR)

    # Every screenshot filename appears (as part of its input path).
    for scene in plan["scenes"]:
        assert any(scene["screenshot"] in arg for arg in argv)

    # Every per-scene caption PNG path appears as an exact input arg.
    for cap in caption_paths(plan, WORKDIR):
        assert cap in argv

    # Audio + low-RAM encode flags.
    assert any("voice.mp3" in arg for arg in argv)
    assert "-threads" in argv
    assert "1" in argv
    assert "libx264" in argv


def test_argv_chains_xfade_and_cut():
    # scenes[0].transition == "crossfade" -> xfade at the 0->1 boundary;
    # scenes[1].transition == "cut"       -> concat at the 1->2 boundary.
    argv = build_render_script(_plan(), WORKDIR)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "xfade=transition=fade" in graph
    assert "concat=n=2:v=1:a=0" in graph
    assert "zoompan=" in graph
    assert "overlay=" in graph


def test_caption_png_is_valid(tmp_path):
    out = tmp_path / "c.png"
    render_caption_png("Hello world this wraps", (1280, 720), out)

    # verify() consumes the file handle, so re-open to inspect attributes.
    Image.open(out).verify()
    img = Image.open(out)
    assert img.size == (1280, 720)
    assert "A" in img.getbands()  # has an alpha channel
    assert img.mode == "RGBA"


def test_unknown_template_falls_back_to_product_demo():
    # Documented behavior: an unknown template_id falls back to product_demo.
    assert get_style("totally-unknown") == get_style("product_demo")

    plan = _plan(template_id="totally-unknown")
    argv = build_render_script(plan, WORKDIR)  # must not raise
    assert any(arg.endswith("out.mp4") for arg in argv)


# --------------------------------------------------------------------------- #
# Expanded xfade transition palette (Task 1.4)
# --------------------------------------------------------------------------- #
def _graph(plan: dict) -> str:
    """Extract the ``-filter_complex`` graph string from a built argv."""
    argv = build_render_script(plan, WORKDIR)
    return argv[argv.index("-filter_complex") + 1]


def _two_scene_plan(transition: str, d0: float = 3.0, d1: float = 2.5) -> dict:
    """A minimal 2-scene plan whose single boundary uses ``transition``."""
    return _plan(
        scenes=[
            {
                "screenshot": "a.png",
                "caption": "Scene A caption",
                "duration_s": d0,
                "transition": transition,
            },
            {
                "screenshot": "b.png",
                "caption": "Scene B caption",
                "duration_s": d1,
                "transition": "cut",
            },
        ]
    )


def test_dissolve_boundary_emits_xfade_dissolve():
    graph = _graph(_two_scene_plan("dissolve"))
    assert "xfade=transition=dissolve" in graph


def test_next_boundary_emits_xfade_smoothleft():
    graph = _graph(_two_scene_plan("next"))
    assert "xfade=transition=smoothleft" in graph


def test_section_boundary_emits_fadeblack_clamped():
    # The 0.7s base fadeblack dip must clamp below the smaller adjacent scene:
    # a 0.5s neighbor floors the dip at 0.9 * 0.5 == 0.45.
    graph = _graph(_two_scene_plan("section", d0=3.0, d1=0.5))
    match = re.search(r"xfade=transition=fadeblack:duration=([0-9.]+)", graph)
    assert match is not None
    duration = float(match.group(1))
    assert duration <= 0.45
    assert duration < 0.5  # strictly below the smaller adjacent scene


def test_cut_boundary_emits_concat():
    graph = _graph(_two_scene_plan("cut"))
    assert "concat=n=2:v=1:a=0" in graph
    assert "xfade=" not in graph


def test_crossfade_offset_math_unchanged():
    # Pre-change behavior for the default 3-scene plan: the 0->1 crossfade uses
    # the product_demo fade (0.5s) at offset 3.0 - 0.5 == 2.5, and the 1->2
    # boundary stays a hard concat.
    graph = _graph(_plan())
    assert "xfade=transition=fade:duration=0.5:offset=2.5" in graph
    assert "concat=n=2:v=1:a=0" in graph
