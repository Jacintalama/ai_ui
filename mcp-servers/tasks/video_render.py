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
  * per scene the filtergraph letterboxes the screenshot (blur-fill or cover),
    applies a smooth Ken Burns ``zoompan``, an optional color grade, then
    ``overlay``s an alpha-faded caption (every stage style-driven),
  * consecutive scenes are joined with an ``xfade`` whose type is mapped from
    the earlier scene's ``transition`` (see :data:`XFADE`), otherwise a plain
    ``concat`` (hard cut),
  * ``voice.mp3`` is mapped as audio, delayed by the intro card so the cards
    stay silent (no ``-shortest``: the video chain bounds the output length),
  * encoded with libx264/veryfast/yuv420p at ``-threads 1`` (low RAM) and
    ``-r 30`` to ``<workdir>/out.mp4``.

Visual style (letterbox, motion, grade, caption look, crossfade length) comes
from ``templates_video`` via :func:`get_style_config`. For now the style is the
documented ``clean_product_demo`` fallback; Task U6 wires the real job style.
"""
from __future__ import annotations

import os
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from templates_video import CaptionStyle, StyleConfig, get_style_config

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

# Intro/outro card timing (seconds). Cards are ADDITIONAL to the 60s scene cap,
# so a finished video runs CARD_DURATION + body (<= 60s) + CARD_DURATION.
CARD_DURATION = 3.0
CARD_FADE = 0.5


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def resolution_size(plan: dict) -> tuple[int, int]:
    """Return ``(width, height)`` for the plan, defaulting to 720p."""
    return RESOLUTIONS.get(plan.get("resolution") or "", RESOLUTIONS[DEFAULT_RESOLUTION])


# --------------------------------------------------------------------------- #
# Path helpers (always POSIX, the render runs on a Linux host)
# --------------------------------------------------------------------------- #
def _screenshot_path(workdir: str, screenshot: str) -> str:
    return f"{workdir}/screenshots/{screenshot}"


def _caption_path(workdir: str, index: int) -> str:
    return f"{workdir}/captions/scene-{index}.png"


def _voice_path(workdir: str) -> str:
    return f"{workdir}/{VOICE_NAME}"


def _intro_card_path(workdir: str) -> str:
    return f"{workdir}/intro.png"


def _outro_card_path(workdir: str) -> str:
    return f"{workdir}/outro.png"


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


# Title-safe inset (fraction of the frame height) kept clear on every edge so
# captions never crowd the broadcast-unsafe margins.
TITLE_SAFE_RATIO = 0.055


def _draw_rounded_band(draw, box, radius, fill) -> None:
    """Draw a rounded backing band, degrading to a square one on old Pillow."""
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    except AttributeError:  # Pillow < 8.2 has no rounded_rectangle
        draw.rectangle(box, fill=fill)


def render_caption_png(
    text: str,
    size: tuple[int, int],
    caption_style: CaptionStyle,
    out_path=None,
    *,
    font_path: str = DEFAULT_FONT_PATH,
) -> Image.Image | str:
    """Render ``text`` as a styled, transparent RGBA caption overlay.

    The look is driven entirely by ``caption_style`` (a :class:`CaptionStyle`):

      * ``font_size_ratio`` sizes the font relative to the frame height,
      * ``position`` aligns the text block ("bottom" | "center" | "top") inside
        the title-safe area,
      * a rounded "glass" band (``band_color`` at ``band_opacity``) sits behind
        the text, unless ``band_opacity`` is 0, in which case the text rides
        bare on its drop shadow (used by bold, bandless social styles),
      * every line gets a soft drop-shadow pass first for legibility.

    When ``out_path`` is given the PNG is written there and the path string is
    returned; otherwise the in-memory :class:`PIL.Image.Image` is returned (the
    offline unit tests use this form). Always RGBA with a real alpha channel.
    """
    width, height = int(size[0]), int(size[1])
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    font_px = max(12, int(round(height * float(caption_style.font_size_ratio))))
    font = _load_font(font_path, font_px)

    margin = int(round(height * TITLE_SAFE_RATIO))
    max_text_width = max(1, width - 2 * margin)
    lines = _wrap_text(draw, text, font, max_text_width)

    line_h = _line_height(draw, font)
    line_gap = int(round(line_h * 0.25))
    block_h = len(lines) * line_h + (len(lines) - 1) * line_gap

    position = caption_style.position
    if position == "top":
        block_top = margin
    elif position == "center":
        block_top = max(margin, (height - block_h) // 2)
    else:  # "bottom" (default)
        block_top = max(margin, height - margin - block_h)

    # Rounded "glass" backing band hugging the text block (skipped when the
    # style asks for no band, e.g. bold social captions).
    band_opacity = float(caption_style.band_opacity)
    if band_opacity > 0:
        widest = max((_text_width(draw, ln, font) for ln in lines), default=0)
        pad_x = int(round(font_px * 0.6))
        pad_y = int(round(font_px * 0.35))
        band_w = min(width - 2 * margin, int(widest) + 2 * pad_x)
        band_left = max(margin, (width - band_w) // 2)
        band_right = min(width - margin, band_left + band_w)
        band_top = max(0, block_top - pad_y)
        band_bottom = min(height, block_top + block_h + pad_y)
        band_alpha = max(0, min(255, int(round(255 * band_opacity))))
        radius = max(8, int(round(font_px * 0.4)))
        bc = caption_style.band_color
        _draw_rounded_band(
            draw,
            [band_left, band_top, band_right, band_bottom],
            radius,
            (bc[0], bc[1], bc[2], band_alpha),
        )

    # Drop-shadow pass, then the bright text on top, centered per line.
    shadow_off = max(1, int(round(font_px * 0.06)))
    shadow_fill = (0, 0, 0, 170)
    text_fill = (255, 255, 255, 255)
    y = block_top
    for line in lines:
        line_w = _text_width(draw, line, font)
        x = max(0, (width - line_w) / 2)
        draw.text((x + shadow_off, y + shadow_off), line, font=font, fill=shadow_fill)
        draw.text((x, y), line, font=font, fill=text_fill)
        y += line_h + line_gap

    if out_path is None:
        return image

    out_str = str(out_path)
    parent = os.path.dirname(out_str)
    if parent:
        os.makedirs(parent, exist_ok=True)
    image.save(out_str, format="PNG")
    return out_str


def render_all_captions(
    plan: dict,
    workdir: str,
    size: tuple[int, int],
    style_config: StyleConfig | None = None,
    *,
    font_path: str = DEFAULT_FONT_PATH,
) -> list[str]:
    """Render one caption PNG per scene using the render's :class:`StyleConfig`.

    Used by the executor (Task 3.2) to materialize ``captions/scene-<i>.png``
    before invoking ffmpeg. ``style_config`` defaults to the plan's resolved
    style (``get_style_config(plan.get("style"))``, which falls back to
    ``clean_product_demo``); Task U6 threads the real job style through here.
    Returns the list of written paths.
    """
    if style_config is None:
        style_config = get_style_config(plan.get("style"))
    paths = caption_paths(plan, workdir)
    for scene, out_path in zip(plan["scenes"], paths):
        render_caption_png(
            scene["caption"],
            size,
            style_config.caption,
            out_path,
            font_path=font_path,
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


def _hex_color(rgb: Sequence[int]) -> str:
    """Format an ``(r, g, b)`` tuple as ffmpeg's ``0xRRGGBB`` color syntax."""
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"0x{r:02X}{g:02X}{b:02X}"


def _letterbox_stmts(index: int, width: int, height: int, letterbox: str) -> list[str]:
    """1.6 letterbox: turn screenshot input ``[{index}:v]`` into ``[base{index}]``.

    * ``blurfill``: the shot is contained over a screen-filling, blurred copy of
      itself, so empty bars are filled instead of black.
    * ``cinema239``: like blurfill, but the shot is contained inside a centered
      2.39:1 cinematic band over the blurred fill.
    * ``none`` (and any unknown value): the shot is scaled to cover and
      center-cropped to the exact frame (no bars at all).
    """
    src = f"[{index}:v]"
    base = f"base{index}"
    if letterbox in ("blurfill", "cinema239"):
        if letterbox == "cinema239":
            fg_h = int(round(width / 2.39))
            fg_scale = (
                f"scale={width}:{fg_h}:force_original_aspect_ratio=decrease,setsar=1"
            )
        else:
            fg_scale = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1"
            )
        return [
            f"{src}split=2[fg{index}][bgsrc{index}]",
            (
                f"[bgsrc{index}]scale={width}:{height}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={width}:{height},boxblur=20:1[bg{index}b]"
            ),
            f"[fg{index}]{fg_scale}[fg{index}c]",
            (
                f"[bg{index}b][fg{index}c]overlay=(W-w)/2:(H-h)/2,"
                f"format=yuv420p[{base}]"
            ),
        ]
    # "none" / unknown: scale to cover, then crop to the exact frame.
    return [
        (
            f"{src}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1[{base}]"
        )
    ]


def _kenburns_stmts(
    index: int,
    width: int,
    height: int,
    frames: int,
    motion: str,
    fps: int = FPS,
) -> list[str]:
    """1.5 Ken Burns: turn ``[base{index}]`` into ``[mot{index}]``.

    ``eased`` alternates a smooth cosine push-in (even scenes) and pull-out (odd
    scenes); ``gentle`` is a slow cosine push-in (up to 1.06x); ``minimal`` does
    no zoom and just aliases ``[base{index}]`` to ``[mot{index}]``. Zoom paths
    supersample to ``2*W`` first so the ``zoompan`` stays jitter-free.
    """
    base = f"[base{index}]"
    out = f"[mot{index}]"
    ss = width * 2
    if motion == "eased":
        if index % 2 == 0:  # push in
            zoom = f"1+0.16*(1-cos(PI*on/{frames}))/2"
        else:  # pull out
            zoom = f"1.16-0.16*(1-cos(PI*on/{frames}))/2"
    elif motion == "gentle":
        zoom = f"1+0.06*(1-cos(PI*on/{frames}))/2"
    else:  # "minimal" / unknown -> no motion, alias base straight through
        return [f"{base}null{out}"]
    return [
        (
            f"{base}scale={ss}:-2,zoompan=z='{zoom}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps}{out}"
        )
    ]


def _grade_stmts(index: int, grade: str) -> list[str]:
    """1.8 color grade: turn ``[mot{index}]`` into ``[grad{index}]``.

    Applies ``grade`` (an ffmpeg filter chain) when non-empty; otherwise aliases
    ``[mot{index}]`` straight through so the label chain stays connected.
    """
    src = f"[mot{index}]"
    out = f"[grad{index}]"
    if grade:
        return [f"{src}{grade}{out}"]
    return [f"{src}null{out}"]


def _caption_fade_stmt(index: int, scene_count: int, duration_s: float) -> str:
    """1.9 animated caption: alpha fade-in/out on caption input ``[{n+index}:v]``.

    Fade lengths scale with the scene (``min(0.3, dur/3)``) so a short scene's
    fade-in and fade-out can never overlap. Produces ``[cap{index}]``.
    """
    caption_input = scene_count + index  # caption inputs follow all screenshots
    dur = float(duration_s)
    fade = min(0.3, dur / 3.0)
    st_out = round(dur - fade, 3)
    return (
        f"[{caption_input}:v]format=rgba,"
        f"fade=t=in:st=0:d={_fmt_num(fade)}:alpha=1,"
        f"fade=t=out:st={_fmt_num(st_out)}:d={_fmt_num(fade)}:alpha=1[cap{index}]"
    )


def _scene_filter_stmts(
    index: int,
    scene_count: int,
    duration_s: float,
    width: int,
    height: int,
    style: StyleConfig,
    fps: int = FPS,
) -> list[str]:
    """Build the multi-statement subgraph for scene ``index``.

    A scene is no longer one comma chain: blurfill is multi-node, so each stage
    owns a distinct label and they wire together in sequence::

        [{index}:v]    -> letterbox (1.6)    -> [base{index}]
        [base{index}]  -> Ken Burns (1.5)    -> [mot{index}]
        [mot{index}]   -> color grade (1.8)  -> [grad{index}]
        [{n+index}:v]  -> caption fade (1.9) -> [cap{index}]
        [grad{index}][cap{index}]overlay=0:0,format=yuv420p -> [v{index}]

    The finished ``[v{index}]`` stream feeds the unchanged ``_chain_stmts``.
    """
    frames = max(1, int(round(float(duration_s) * fps)))
    stmts: list[str] = []
    stmts += _letterbox_stmts(index, width, height, style.letterbox)
    stmts += _kenburns_stmts(index, width, height, frames, style.motion, fps)
    stmts += _grade_stmts(index, style.grade)
    stmts.append(_caption_fade_stmt(index, scene_count, duration_s))
    stmts.append(
        f"[grad{index}][cap{index}]overlay=0:0,format=yuv420p[v{index}]"
    )
    return stmts


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
) -> tuple[list[str], str, float]:
    """Fold the per-scene ``[v{i}]`` streams into one final video label.

    Boundary i->i+1 uses scene ``i``'s ``transition``. Transitions in
    :data:`XFADE` emit an ``xfade`` of the mapped type (with an accumulating
    ``offset``); anything else (e.g. ``cut``) emits a hard-cut ``concat``.

    Every xfade dip is clamped to ``0.9 * min(prev_scene, cur_scene)`` so a
    fade can never exceed the shorter of its two adjacent scenes (a 0.7s
    ``section`` dip is invalid against a 0.5s scene, for example). Returns
    ``(statements, final_label, accumulated_duration)`` where the accumulated
    duration is the body length after xfade overlaps are subtracted (used to
    offset the trailing outro card).
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

    return stmts, final_label, acc_duration


def build_filtergraph(
    scenes: Sequence[dict],
    width: int,
    height: int,
    style: StyleConfig,
    fps: int = FPS,
) -> tuple[str, str, float]:
    """Build the body ``-filter_complex`` string for the scenes.

    Returns ``(graph, vlabel, total_duration)``: the joined per-scene subgraph +
    transition chain, the final video label, and the body duration after xfade
    overlaps (the intro/outro cards are stitched on separately by
    :func:`build_render_script`).

    Pure and unit-testable: no ffmpeg, no disk access. Each per-scene subgraph
    is style-driven (letterbox/motion/grade/caption from ``style``); the
    scene-to-scene transition chain uses the embedded ``style.caption`` for its
    crossfade timing.
    """
    if not scenes:
        raise ValueError("cannot build a filtergraph with no scenes")

    n = len(scenes)
    stmts: list[str] = []
    for i, scene in enumerate(scenes):
        stmts.extend(
            _scene_filter_stmts(i, n, scene["duration_s"], width, height, style, fps)
        )

    chain, final_label, total_duration = _chain_stmts(scenes, style.caption)
    stmts.extend(chain)
    return ";".join(stmts), final_label, total_duration


def _card_bookend_stmts(
    body_label: str,
    body_duration: float,
    intro_color_idx: int,
    outro_color_idx: int,
    intro_png_idx: int,
    outro_png_idx: int,
) -> tuple[list[str], str]:
    """Stitch the intro/outro cards onto the body as xfade bookends.

    Each card overlays its Pillow-rendered PNG onto a solid lavfi color canvas,
    fades in and out, and ends in the same pixel format as the body ``[v{i}]``
    streams so ``xfade`` accepts it. The intro crossfades into the body at the
    head and the body crossfades into the outro at the tail, both with an
    accumulating offset, so the cards are ADDITIONAL to the body duration.
    Returns ``(statements, final_label)``.
    """
    fade_out_start = _fmt_num(round(CARD_DURATION - 0.6, 4))
    intro_stmt = (
        f"[{intro_color_idx}:v][{intro_png_idx}:v]overlay=0:0,"
        f"fade=t=in:st=0:d=0.4,"
        f"fade=t=out:st={fade_out_start}:d=0.5,format=yuv420p[intro]"
    )
    outro_stmt = (
        f"[{outro_color_idx}:v][{outro_png_idx}:v]overlay=0:0,"
        f"fade=t=in:st=0:d=0.4,"
        f"fade=t=out:st={fade_out_start}:d=0.5,format=yuv420p[outro]"
    )
    head_offset = _fmt_num(round(CARD_DURATION - CARD_FADE, 4))
    tail_offset = _fmt_num(round(CARD_DURATION + body_duration - CARD_FADE, 4))
    head_stmt = (
        f"[intro]{body_label}xfade=transition=fade:"
        f"duration={_fmt_num(CARD_FADE)}:offset={head_offset}[ihead]"
    )
    tail_stmt = (
        f"[ihead][outro]xfade=transition=fade:"
        f"duration={_fmt_num(CARD_FADE)}:offset={tail_offset}[vout]"
    )
    return [intro_stmt, outro_stmt, head_stmt, tail_stmt], "[vout]"


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
    style = get_style_config(plan.get("style"))
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
    voice_index = 2 * n

    # Inputs 2n+1..2n+4 (the HIGHEST indices, appended last so the hardcoded
    # caption index [{n+i}:v] stays valid): two lavfi color canvases for the
    # intro/outro cards, then the two Pillow-rendered card PNGs overlaid on
    # them. The cards are stitched onto the body as xfade bookends below.
    intro_color_idx = voice_index + 1
    outro_color_idx = voice_index + 2
    intro_png_idx = voice_index + 3
    outro_png_idx = voice_index + 4
    card_bg = _hex_color(style.cards.get("bg_color", (0, 0, 0)))
    card_size = f"{width}x{height}"
    card_dur = _fmt_num(CARD_DURATION)
    argv += [
        "-f", "lavfi",
        "-t", card_dur,
        "-i", f"color=c={card_bg}:s={card_size}:r={FPS}",
        "-f", "lavfi",
        "-t", card_dur,
        "-i", f"color=c={card_bg}:s={card_size}:r={FPS}",
        "-loop", "1",
        "-t", card_dur,
        "-i", _intro_card_path(workdir),
        "-loop", "1",
        "-t", card_dur,
        "-i", _outro_card_path(workdir),
    ]

    body_graph, body_label, body_duration = build_filtergraph(
        scenes, width, height, style
    )
    card_stmts, video_label = _card_bookend_stmts(
        body_label,
        body_duration,
        intro_color_idx,
        outro_color_idx,
        intro_png_idx,
        outro_png_idx,
    )
    # Delay the single narration track by the intro so the cards stay silent:
    # the intro plays before any narration and the narration ends before the
    # outro. ``-shortest`` is intentionally omitted: the deterministic video
    # chain bounds the output length, and the trailing outro is silent.
    audio_stmt = f"[{voice_index}:a]adelay={int(CARD_DURATION * 1000)}:all=1[aud]"
    filtergraph = ";".join([body_graph, *card_stmts, audio_stmt])

    argv += [
        "-filter_complex", filtergraph,
        "-map", video_label,
        "-map", "[aud]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        "-r", str(FPS),
        _out_path(workdir),
    ]
    return argv
