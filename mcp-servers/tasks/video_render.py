"""Pure ffmpeg-argv + caption-PNG builders for the slideshow video renderer.

This module is deliberately side-effect free except for one thing: writing
caption PNGs to disk (via Pillow). It never runs ffmpeg. ``build_render_script``
returns the ``list[str]`` argv for a *single* ffmpeg invocation, which the
host-side executor (Task 3.2) runs over SSH. Keeping it pure makes the
filtergraph unit-testable offline (ffmpeg is only installed on the render host).

Pipeline shape per scene, all driven by the validated plan
(see ``video_plan.PLAN_SCHEMA``):

  * each scene's screenshot is a looped still image input
    (``-loop 1 -t <duration_s>``),
  * each scene's pre-rendered caption PNG is a second looped image input,
  * the filtergraph scales+pads the screenshot to the target resolution,
    applies a gentle Ken Burns ``zoompan``, then ``overlay``s the caption,
  * consecutive scenes are joined with an ``xfade`` whose type is mapped from
    the earlier scene's ``transition`` (see :data:`XFADE`), otherwise a plain
    ``concat`` (hard cut),
  * ``voice.mp3`` is the final input, mapped as audio with ``-shortest``,
  * encoded with libx264/veryfast/yuv420p at ``-threads 1`` (low RAM) and
    ``-r 30`` to ``<workdir>/out.mp4``.

Template style (caption look + crossfade length) comes from
``templates_video`` and only parameterizes appearance, never the graph shape.
"""
from __future__ import annotations

import os
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from templates_video import CaptionStyle, get_style

# Target pixel dimensions per plan ``resolution``. Default to 720p when the
# plan omits it or uses an unrecognized value.
RESOLUTIONS: dict[str, tuple[int, int]] = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
DEFAULT_RESOLUTION = "720p"

# Bundled DejaVu Bold on the render host (apt: fonts-dejavu). Tests fall back to
# Pillow's built-in font when this file is absent, so they run fully offline.
DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

FPS = 30
OUTPUT_NAME = "out.mp4"
VOICE_NAME = "voice.mp3"


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def resolution_size(plan: dict) -> tuple[int, int]:
    """Return ``(width, height)`` for the plan, defaulting to 720p."""
    return RESOLUTIONS.get(plan.get("resolution") or "", RESOLUTIONS[DEFAULT_RESOLUTION])


# --------------------------------------------------------------------------- #
# Path helpers (always POSIX — the render runs on a Linux host)
# --------------------------------------------------------------------------- #
def _screenshot_path(workdir: str, screenshot: str) -> str:
    return f"{workdir}/screenshots/{screenshot}"


def _caption_path(workdir: str, index: int) -> str:
    return f"{workdir}/captions/scene-{index}.png"


def _voice_path(workdir: str) -> str:
    return f"{workdir}/{VOICE_NAME}"


def _out_path(workdir: str) -> str:
    return f"{workdir}/{OUTPUT_NAME}"


def caption_paths(plan: dict, workdir: str) -> list[str]:
    """Return the caption PNG output path for every scene, in order."""
    workdir = str(workdir).rstrip("/")
    return [_caption_path(workdir, i) for i in range(len(plan["scenes"]))]


# --------------------------------------------------------------------------- #
# Caption rendering (Pillow -> transparent PNG). Runs offline.
# --------------------------------------------------------------------------- #
def _load_font(font_path: str, size_px: int) -> ImageFont.ImageFont:
    """Load the requested TrueType font, falling back to Pillow's default.

    The DejaVu font is bundled on the render host; in tests it is absent, so we
    fall back to ``load_default`` and still produce a valid PNG.
    """
    try:
        return ImageFont.truetype(font_path, size_px)
    except OSError:
        try:
            return ImageFont.load_default(size_px)  # Pillow >= 10 accepts a size
        except TypeError:  # very old Pillow
            return ImageFont.load_default()


def _line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    try:
        ascent, descent = font.getmetrics()
        return int(ascent + descent)
    except AttributeError:
        bbox = draw.textbbox((0, 0), "Ag", font=font)
        return int(bbox[3] - bbox[1])


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: float,
) -> list[str]:
    """Greedy word wrap to fit ``max_width`` pixels."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if _text_width(draw, trial, font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_caption_png(
    text: str,
    size: tuple[int, int],
    out_path,
    *,
    font_path: str = DEFAULT_FONT_PATH,
    font_size_ratio: float = 0.045,
    position: str = "bottom",
    band_color: tuple[int, int, int] = (0, 0, 0),
    band_opacity: float = 0.55,
    text_color: tuple[int, int, int] = (255, 255, 255),
    margin_ratio: float = 0.045,
) -> str:
    """Draw ``text`` onto a transparent RGBA PNG of ``size`` and save it.

    The text is word-wrapped, drawn over a semi-transparent backing band for
    legibility, and aligned to ``position`` ("bottom" | "center" | "top").
    Returns the saved path. Produces a valid PNG with an alpha channel.
    """
    width, height = int(size[0]), int(size[1])
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    font_px = max(12, int(round(height * font_size_ratio)))
    font = _load_font(font_path, font_px)

    margin = int(round(height * margin_ratio))
    max_text_width = max(1, width - 2 * margin)
    lines = _wrap_text(draw, text, font, max_text_width)

    line_h = _line_height(draw, font)
    line_gap = int(round(line_h * 0.25))
    block_h = len(lines) * line_h + (len(lines) - 1) * line_gap

    if position == "top":
        block_top = margin
    elif position == "center":
        block_top = max(margin, (height - block_h) // 2)
    else:  # "bottom" (default)
        block_top = max(margin, height - margin - block_h)

    # Semi-transparent full-width backing band behind the text block.
    band_pad = int(round(height * 0.02))
    band_alpha = max(0, min(255, int(round(255 * band_opacity))))
    band_top = max(0, block_top - band_pad)
    band_bottom = min(height, block_top + block_h + band_pad)
    draw.rectangle(
        [0, band_top, width, band_bottom],
        fill=(band_color[0], band_color[1], band_color[2], band_alpha),
    )

    # Centered text lines, fully opaque, drawn on top of the band.
    y = block_top
    for line in lines:
        line_w = _text_width(draw, line, font)
        x = max(0, (width - line_w) / 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(text_color[0], text_color[1], text_color[2], 255),
        )
        y += line_h + line_gap

    out_str = str(out_path)
    parent = os.path.dirname(out_str)
    if parent:
        os.makedirs(parent, exist_ok=True)
    image.save(out_path, format="PNG")
    return out_str


def render_all_captions(
    plan: dict,
    workdir: str,
    size: tuple[int, int],
    *,
    font_path: str = DEFAULT_FONT_PATH,
) -> list[str]:
    """Render one caption PNG per scene using the plan's template style.

    Used by the executor (Task 3.2) to materialize ``captions/scene-<i>.png``
    before invoking ffmpeg. Returns the list of written paths.
    """
    style = get_style(plan.get("template_id"))
    paths = caption_paths(plan, workdir)
    for scene, out_path in zip(plan["scenes"], paths):
        render_caption_png(
            scene["caption"],
            size,
            out_path,
            font_path=font_path,
            font_size_ratio=style.font_size_ratio,
            position=style.position,
            band_color=style.band_color,
            band_opacity=style.band_opacity,
        )
    return paths


# --------------------------------------------------------------------------- #
# ffmpeg argv builder (pure)
# --------------------------------------------------------------------------- #
def _fmt_num(value: float) -> str:
    """Format a number for an ffmpeg arg: integers without a trailing ``.0``."""
    f = float(value)
    if f.is_integer():
        return str(int(f))
    return repr(round(f, 4))


def _scale_pad_filter(width: int, height: int) -> str:
    """Scale to fit then pad to exactly ``width x height`` (letterbox-safe)."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )


def _zoompan_filter(width: int, height: int, frames: int, fps: int = FPS) -> str:
    """A gentle Ken Burns push-in over ``frames`` output frames."""
    return (
        f"zoompan=z='min(zoom+0.0015,1.08)':d={frames}:"
        f"s={width}x{height}:fps={fps}"
    )


def _overlay_filter() -> str:
    """Overlay the (full-frame) caption PNG at the origin, in yuv420p.

    The caption PNG already carries the text at the right position, so the
    overlay is always at 0:0. Normalizing to yuv420p here keeps every scene
    stream format-compatible for xfade/concat downstream.
    """
    return "overlay=0:0:format=auto,format=yuv420p"


def _scene_filter_stmts(
    index: int,
    scene_count: int,
    duration_s: float,
    width: int,
    height: int,
    fps: int = FPS,
) -> list[str]:
    """Filter statements turning screenshot input ``index`` + its caption input
    into a finished ``[v{index}]`` scene stream."""
    frames = max(1, int(round(float(duration_s) * fps)))
    caption_input = scene_count + index  # caption inputs follow all screenshots
    return [
        f"[{index}:v]{_scale_pad_filter(width, height)},"
        f"{_zoompan_filter(width, height, frames, fps)}[bg{index}]",
        f"[bg{index}][{caption_input}:v]{_overlay_filter()}[v{index}]",
    ]


# Logical scene transitions -> ffmpeg ``xfade`` transition names. Anything not
# in this map (notably ``cut``) falls back to a hard-cut ``concat``.
XFADE: dict[str, str] = {
    "crossfade": "fade",
    "dissolve": "dissolve",
    "next": "smoothleft",
    "section": "fadeblack",
}

# ``section`` boundaries get a longer "to black and back" dip than the
# template's normal crossfade. Still clamped to the adjacent scenes below.
SECTION_FADE: float = 0.7


def _chain_stmts(
    scenes: Sequence[dict],
    style: CaptionStyle,
) -> tuple[list[str], str]:
    """Fold the per-scene ``[v{i}]`` streams into one final video label.

    Boundary i->i+1 uses scene ``i``'s ``transition``. Transitions in
    :data:`XFADE` emit an ``xfade`` of the mapped type (with an accumulating
    ``offset``); anything else (e.g. ``cut``) emits a hard-cut ``concat``.

    Every xfade dip is clamped to ``0.9 * min(prev_scene, cur_scene)`` so a
    fade can never exceed the shorter of its two adjacent scenes (a 0.7s
    ``section`` dip is invalid against a 0.5s scene, for example). Returns
    ``(statements, final_label)``.
    """
    stmts: list[str] = []
    final_label = "[v0]"
    # Running duration of the accumulated stream; xfade overlaps shorten it.
    acc_duration = float(scenes[0]["duration_s"])

    for i in range(1, len(scenes)):
        prev_transition = scenes[i - 1].get("transition", "cut")
        nxt = f"[v{i}]"
        out = f"[x{i}]"
        prev_dur = float(scenes[i - 1]["duration_s"])
        scene_dur = float(scenes[i]["duration_s"])
        xfade_type = XFADE.get(prev_transition)
        if xfade_type is not None:
            base_fade = (
                SECTION_FADE
                if prev_transition == "section"
                else float(style.fade_duration)
            )
            # Clamp the dip below the shorter adjacent scene so it stays valid.
            fade = min(base_fade, 0.9 * min(prev_dur, scene_dur))
            offset = max(0.0, round(acc_duration - fade, 4))
            stmts.append(
                f"{final_label}{nxt}xfade=transition={xfade_type}:"
                f"duration={_fmt_num(fade)}:offset={_fmt_num(offset)}{out}"
            )
            acc_duration = acc_duration + scene_dur - fade
        else:  # hard cut
            stmts.append(f"{final_label}{nxt}concat=n=2:v=1:a=0{out}")
            acc_duration = acc_duration + scene_dur
        final_label = out

    return stmts, final_label


def build_filtergraph(
    scenes: Sequence[dict],
    width: int,
    height: int,
    style: CaptionStyle,
    fps: int = FPS,
) -> tuple[str, str]:
    """Build the full ``-filter_complex`` string and return ``(graph, vlabel)``.

    Pure and unit-testable: no ffmpeg, no disk access.
    """
    if not scenes:
        raise ValueError("cannot build a filtergraph with no scenes")

    n = len(scenes)
    stmts: list[str] = []
    for i, scene in enumerate(scenes):
        stmts.extend(
            _scene_filter_stmts(i, n, scene["duration_s"], width, height, fps)
        )

    chain, final_label = _chain_stmts(scenes, style)
    stmts.extend(chain)
    return ";".join(stmts), final_label


def build_render_script(plan: dict, workdir: str) -> list[str]:
    """Build the single-invocation ffmpeg ``argv`` for ``plan``.

    Pure: returns a ``list[str]``; does not run ffmpeg and writes nothing.
    Caption PNGs are expected to already exist (see ``render_all_captions``).
    """
    workdir = str(workdir).rstrip("/")
    scenes = plan["scenes"]
    if not scenes:
        raise ValueError("plan has no scenes")

    width, height = resolution_size(plan)
    style = get_style(plan.get("template_id"))
    n = len(scenes)

    argv: list[str] = ["ffmpeg", "-y"]

    # Inputs 0..n-1: screenshots, each a looped still for its scene duration.
    for scene in scenes:
        argv += [
            "-loop", "1",
            "-t", _fmt_num(scene["duration_s"]),
            "-i", _screenshot_path(workdir, scene["screenshot"]),
        ]

    # Inputs n..2n-1: per-scene caption PNGs, looped to match each scene.
    for i, scene in enumerate(scenes):
        argv += [
            "-loop", "1",
            "-t", _fmt_num(scene["duration_s"]),
            "-i", _caption_path(workdir, i),
        ]

    # Input 2n: the narration track.
    argv += ["-i", _voice_path(workdir)]

    filtergraph, video_label = build_filtergraph(scenes, width, height, style)
    voice_index = 2 * n

    argv += [
        "-filter_complex", filtergraph,
        "-map", video_label,
        "-map", f"{voice_index}:a",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-r", str(FPS),
        "-shortest",
        _out_path(workdir),
    ]
    return argv
