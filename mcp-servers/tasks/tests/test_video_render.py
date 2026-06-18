"""Offline structural tests for video_render.

ffmpeg is not installed locally and the real encode happens on the render host
at deploy time, so these tests verify the *structure* of the produced ffmpeg
argv (not an actual encode). Caption-PNG generation uses Pillow and IS exercised
for real here.
"""
import re

from PIL import Image

from templates_video import (
    CaptionStyle,
    StyleConfig,
    get_style,
    get_style_config,
)
from video_render import (
    CARD_DURATION,
    CARD_FADE,
    RESOLUTIONS,
    _intro_card_path,
    _outro_card_path,
    _scene_filter_stmts,
    _voice_path,
    build_filtergraph,
    build_render_script,
    caption_paths,
    render_caption_png,
    resolution_size,
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
    assert argv[argv.index("-threads") + 1] == "2"
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
    cap = get_style_config(None).caption  # default clean_product_demo caption
    render_caption_png("Hello world this wraps", (1280, 720), cap, out)

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
    # The cut boundary is a hard concat; the only xfades are the intro/outro
    # card bookends (always crossfaded onto the body).
    assert "concat=n=2:v=1:a=0" in graph
    assert graph.count("xfade=transition=fade") == 2


def test_crossfade_offset_math_unchanged():
    # The default plan now resolves to the clean_product_demo StyleConfig, whose
    # caption fade is 0.4s, so the 0->1 crossfade uses a 0.4s fade at offset
    # 3.0 - 0.4 == 2.6, and the 1->2 boundary stays a hard concat. The offset
    # math itself (acc_duration - fade) is unchanged.
    graph = _graph(_plan())
    assert "xfade=transition=fade:duration=0.4:offset=2.6" in graph
    assert "concat=n=2:v=1:a=0" in graph


# --------------------------------------------------------------------------- #
# Per-scene subgraph: smooth Ken Burns + blurfill letterbox + grade + animated
# styled captions (Tasks 1.5-1.9)
# --------------------------------------------------------------------------- #
def _caption_style(**overrides) -> CaptionStyle:
    base = dict(
        font_size_ratio=0.048,
        position="bottom",
        band_color=(17, 24, 39),
        band_opacity=0.6,
        fade_duration=0.4,
    )
    base.update(overrides)
    return CaptionStyle(**base)


def _style(
    *,
    motion: str = "gentle",
    grade: str = "",
    letterbox: str = "blurfill",
    caption: CaptionStyle | None = None,
) -> StyleConfig:
    """A StyleConfig the per-scene builders can be driven by directly."""
    return StyleConfig(
        id="unit-test",
        caption=caption or _caption_style(),
        transitions={"crossfade": "fade"},
        motion=motion,
        grade=grade,
        letterbox=letterbox,
        cards={},
        music="none",
        music_level=0.2,
    )


# --- 1.5 Ken Burns motion --------------------------------------------------- #
def test_motion_eased_pushin_on_even_pullout_on_odd():
    style = _style(motion="eased", letterbox="none")
    w, h = 1280, 720
    frames = round(3.0 * 30)  # FPS=30

    even = ";".join(_scene_filter_stmts(0, 2, 3.0, w, h, style))
    odd = ";".join(_scene_filter_stmts(1, 2, 3.0, w, h, style))

    # Even index -> cosine push-in, supersampled to 2*W before the zoompan.
    assert f"scale={2 * w}:-2" in even
    assert f"zoompan=z='1+0.16*(1-cos(PI*on/{frames}))/2'" in even
    assert "[base0]" in even and "[mot0]" in even

    # Odd index -> cosine pull-out, same supersample.
    assert f"scale={2 * w}:-2" in odd
    assert f"zoompan=z='1.16-0.16*(1-cos(PI*on/{frames}))/2'" in odd


def test_motion_minimal_emits_no_zoompan():
    style = _style(motion="minimal", letterbox="none")
    stmts = ";".join(_scene_filter_stmts(0, 1, 3.0, 1280, 720, style))
    assert "zoompan=" not in stmts
    # mot is aliased straight off base (a null passthrough), no zoom at all.
    assert "[base0]null[mot0]" in stmts


# --- 1.6 letterbox ---------------------------------------------------------- #
def test_letterbox_blurfill_emits_split_boxblur_overlay():
    style = _style(letterbox="blurfill", motion="minimal")
    stmts = ";".join(_scene_filter_stmts(0, 1, 3.0, 1280, 720, style))
    assert "[0:v]split=2" in stmts
    assert "boxblur=20:1" in stmts
    assert "overlay=(W-w)/2:(H-h)/2" in stmts
    assert "[base0]" in stmts  # blurfill subgraph terminates in [base0]


def test_letterbox_none_emits_scale_cover_crop():
    style = _style(letterbox="none", motion="minimal")
    stmts = ";".join(_scene_filter_stmts(0, 1, 3.0, 1280, 720, style))
    assert "split=2" not in stmts
    assert "force_original_aspect_ratio=increase" in stmts
    assert "crop=1280:720" in stmts
    assert "[base0]" in stmts


# --- 1.7 full per-scene label chain ----------------------------------------- #
def test_scene_subgraph_label_chain_connects_to_v_output():
    style = _style(motion="eased", grade="eq=contrast=1.06", letterbox="blurfill")
    stmts = _scene_filter_stmts(0, 2, 3.0, 1280, 720, style)
    joined = ";".join(stmts)

    # [0:v] -> [base0] -> [mot0] -> [grad0]; caption [n:v] -> [cap0];
    # then [grad0][cap0] overlay -> [v0] (no orphan label, ends in [v0]).
    assert joined.startswith("[0:v]")
    for label in ("[base0]", "[mot0]", "[grad0]", "[cap0]"):
        assert label in joined
    assert "[2:v]format=rgba" in joined  # caption input for scene 0 is index n+0
    assert "[grad0][cap0]overlay=0:0,format=yuv420p,settb=AVTB[v0]" in joined
    assert joined.rstrip().endswith("[v0]")


# --- 1.8 color grade -------------------------------------------------------- #
def test_grade_applied_when_style_grade_nonempty():
    grade = "eq=contrast=1.06:saturation=1.12,curves=all='0/0 1/1'"
    style = _style(grade=grade, motion="minimal", letterbox="none")
    joined = ";".join(_scene_filter_stmts(0, 1, 3.0, 1280, 720, style))
    assert f"[mot0]{grade}[grad0]" in joined


def test_grade_aliased_when_style_grade_empty():
    style = _style(grade="", motion="minimal", letterbox="none")
    joined = ";".join(_scene_filter_stmts(0, 1, 3.0, 1280, 720, style))
    assert "[mot0]null[grad0]" in joined  # aliased, not graded
    assert "eq=" not in joined and "curves=" not in joined


# --- 1.9 animated captions -------------------------------------------------- #
def test_caption_alpha_fade_scales_to_short_scene():
    style = _style(motion="minimal", letterbox="none")
    dur = 0.5
    joined = ";".join(_scene_filter_stmts(0, 1, dur, 1280, 720, style))

    assert "[1:v]format=rgba" in joined  # caption input for scene 0 (n=1) is 1
    m_in = re.search(r"fade=t=in:st=0:d=([0-9.]+):alpha=1", joined)
    m_out = re.search(r"fade=t=out:st=([0-9.]+):d=([0-9.]+):alpha=1", joined)
    assert m_in is not None and m_out is not None

    fin = float(m_in.group(1))
    st_out = float(m_out.group(1))
    fout = float(m_out.group(2))

    assert fin == fout
    assert fin <= 0.167  # min(0.3, 0.5/3) ~= 0.1667
    assert fin + fout < dur  # the two fades never overlap on a 0.5s scene
    assert st_out >= fin  # out-fade starts only after the in-fade completes
    assert st_out + fout <= dur + 1e-6


def test_caption_fade_full_length_on_long_scene():
    # A 3.0s scene caps each fade at 0.3s and starts the out-fade at 2.7s.
    style = _style(motion="minimal", letterbox="none")
    joined = ";".join(_scene_filter_stmts(0, 1, 3.0, 1280, 720, style))
    assert "fade=t=in:st=0:d=0.3:alpha=1" in joined
    assert "fade=t=out:st=2.7:d=0.3:alpha=1" in joined


def test_render_caption_png_returns_styled_rgba_image():
    cap = _caption_style(font_size_ratio=0.05, band_opacity=0.6)
    img = render_caption_png(
        "Hello styled caption that should wrap across several lines", (1280, 720), cap
    )
    assert img.mode == "RGBA"
    assert img.size == (1280, 720)
    # Something was actually drawn (band and/or text -> non-zero alpha).
    assert img.getchannel("A").getextrema()[1] > 0


def test_render_caption_png_bandless_style_still_valid():
    # band_opacity == 0 (e.g. snappy_social): bold text + shadow, no band.
    cap = _caption_style(position="center", band_opacity=0.0, font_size_ratio=0.072)
    img = render_caption_png("No band here", (1280, 720), cap)
    assert img.mode == "RGBA"
    assert img.size == (1280, 720)
    assert img.getchannel("A").getextrema()[1] > 0


# --- end-to-end smoke with the default + an explicit StyleConfig ------------ #
def test_build_render_script_default_style_smoke():
    plan = _plan()
    argv = build_render_script(plan, WORKDIR)
    assert isinstance(argv, list)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "[v0]" in graph
    assert "xfade=" in graph  # 0->1 crossfade boundary
    assert "concat=n=2:v=1:a=0" in graph  # 1->2 cut boundary


def test_build_filtergraph_with_explicit_cinematic_style():
    style = get_style_config("cinematic")
    scenes = _plan()["scenes"]
    graph, vlabel, total = build_filtergraph(scenes, 1280, 720, style)
    assert isinstance(vlabel, str) and vlabel
    assert total > 0
    for label in ("[v0]", "[v1]", "[v2]"):
        assert label in graph
    # cinematic letterbox is cinema239 -> blurred-fill split subgraph present.
    assert "split=2" in graph
    # cinematic grade chain is present (eq from its StyleConfig).
    assert "eq=contrast=1.06" in graph


# --------------------------------------------------------------------------- #
# 1.10 intro/outro cards: extra inputs, bookend stitching, silent cards, and a
# fully-connected filtergraph across xfade / cut / single-scene bodies.
# --------------------------------------------------------------------------- #
def _single_scene_plan() -> dict:
    return _plan(
        scenes=[
            {
                "screenshot": "only.png",
                "caption": "The only scene",
                "duration_s": 4.0,
                "transition": "crossfade",
            }
        ]
    )


def test_card_inputs_appended_after_voice():
    argv = build_render_script(_plan(), WORKDIR)
    joined = " ".join(argv)
    # Two lavfi color canvases for the cards.
    assert joined.count("-f lavfi") == 2
    assert "color=c=" in joined
    # The card PNG paths are referenced as looped inputs.
    assert _intro_card_path(WORKDIR) in argv
    assert _outro_card_path(WORKDIR) in argv
    # The new inputs come AFTER the voice input so [{n+i}:v] caption indices
    # (which depend on input order) stay valid.
    voice_pos = argv.index(_voice_path(WORKDIR))
    lavfi_pos = argv.index("lavfi")
    intro_png_pos = argv.index(_intro_card_path(WORKDIR))
    assert voice_pos < lavfi_pos
    assert voice_pos < intro_png_pos


def test_filtergraph_bookends_cards_and_maps_vout():
    argv = build_render_script(_plan(), WORKDIR)
    graph = argv[argv.index("-filter_complex") + 1]
    # The intro/outro card subgraphs exist...
    assert "[intro]" in graph
    assert "[outro]" in graph
    # ...and are stitched as head and tail of the xfade chain.
    assert "[ihead]" in graph
    assert graph.rstrip().endswith("[aud]")  # audio branch is last
    assert "[vout]" in graph
    # The mapped video stream is the bookended output.
    assert argv[argv.index("-map") + 1] == "[vout]"


def test_voice_delayed_and_no_shortest():
    argv = build_render_script(_plan(), WORKDIR)
    graph = argv[argv.index("-filter_complex") + 1]
    # The narration is delayed by the 3s intro so the cards are silent.
    assert "adelay=3000:all=1[aud]" in graph
    # Audio is mapped from the delayed branch, not the raw voice input.
    assert "[aud]" in argv
    # -shortest must be gone, or it would truncate the trailing silent outro.
    assert "-shortest" not in argv


def _label_io(graph: str):
    """Return ``(produced_labels, consumed_labels)`` for a filter_complex.

    Each ``;``-separated statement consumes the run of ``[label]`` at its start
    and produces the run at its end (ffmpeg filterchain syntax). Input pads like
    ``0:v`` / ``5:a`` are consumed but never produced.
    """
    label_re = re.compile(r"\[([^\]]+)\]")
    produced: list[str] = []
    consumed: list[str] = []
    for stmt in graph.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        lead = re.match(r"^((?:\[[^\]]+\])+)", stmt)
        trail = re.search(r"((?:\[[^\]]+\])+)$", stmt)
        if lead:
            consumed += label_re.findall(lead.group(1))
        if trail:
            produced += label_re.findall(trail.group(1))
    return produced, consumed


def _assert_fully_connected(graph: str):
    produced, consumed = _label_io(graph)
    # No label is produced by two statements.
    assert len(produced) == len(set(produced)), (
        f"duplicate label producer in: {sorted(produced)}"
    )
    input_pad = re.compile(r"^\d+:[va]$")
    produced_set = set(produced)
    # Every consumed label is produced upstream or is an ffmpeg input pad.
    for c in consumed:
        assert c in produced_set or input_pad.match(c), f"undefined label [{c}]"
    # Every produced label is consumed, except the two mapped outputs.
    for p in produced_set:
        if p in ("vout", "aud"):
            continue
        assert p in consumed, f"orphan label [{p}]"


def test_filtergraph_fully_connected_xfade_body():
    graph = _graph(_two_scene_plan("crossfade"))
    _assert_fully_connected(graph)


def test_filtergraph_fully_connected_cut_body():
    graph = _graph(_two_scene_plan("cut"))
    _assert_fully_connected(graph)


def test_timebase_normalized_so_cut_plus_cards_dont_mismatch():
    # ffmpeg's concat (a hard cut) forces a microsecond timebase on its output;
    # the lavfi color cards are 1/30. Without a shared timebase the bookend (and
    # post-cut) xfades fail at render time with "timebase do not match". Pin
    # every scene + card to AVTB so they always agree. (Caught only on real
    # ffmpeg, hence this string guard.)
    graph = _graph(_two_scene_plan("cut"))
    # every scene output is normalized
    assert "format=yuv420p,settb=AVTB[v0]" in graph
    assert "format=yuv420p,settb=AVTB[v1]" in graph
    # both cards are normalized to the same timebase
    assert "format=yuv420p,settb=AVTB[intro]" in graph
    assert "format=yuv420p,settb=AVTB[outro]" in graph


def test_filtergraph_fully_connected_single_scene():
    graph = _graph(_single_scene_plan())
    _assert_fully_connected(graph)
    # The single scene seeds [v0], which is timebase-normalized to [btb] before
    # the intro bookends onto it.
    assert "[v0]settb=AVTB[btb]" in graph
    assert "[intro][btb]xfade" in graph


def test_explicit_style_overrides_plan_independent_of_template():
    # The visual look is keyed off the passed style id, NOT template_id.
    plan = _plan(template_id="product_demo")
    default_argv = build_render_script(plan, WORKDIR)
    default_graph = default_argv[default_argv.index("-filter_complex") + 1]
    # The default resolves clean_product_demo: no cinematic grade.
    assert "eq=contrast=1.06" not in default_graph

    cine_argv = build_render_script(plan, WORKDIR, style="cinematic")
    cine_graph = cine_argv[cine_argv.index("-filter_complex") + 1]
    # Explicit "cinematic" selects the cinematic StyleConfig: grade chain +
    # cinema239 blurred-fill letterbox.
    assert "eq=contrast=1.06" in cine_graph
    assert "split=2" in cine_graph


def test_unknown_style_falls_back_to_default():
    plan = _plan()
    argv = build_render_script(plan, WORKDIR, style="not-a-real-style")
    graph = argv[argv.index("-filter_complex") + 1]
    # Falls back to clean_product_demo (no cinematic grade), never raises.
    assert "eq=contrast=1.06" not in graph


def test_delivery_grade_encode_tail():
    argv = build_render_script(_plan(), WORKDIR)

    def _val(flag):
        return argv[argv.index(flag) + 1]

    assert _val("-c:v") == "libx264"
    assert _val("-preset") == "veryfast"
    assert _val("-crf") == "21"
    assert _val("-pix_fmt") == "yuv420p"
    assert _val("-threads") == "2"
    assert _val("-r") == "30"
    assert _val("-c:a") == "aac"
    assert _val("-b:a") == "192k"
    assert _val("-movflags") == "+faststart"
    # Phase 1 still maps the single (delayed) voice branch; music arrives later.
    assert "[aud]" in argv
    assert argv[-1].endswith("out.mp4")


def test_card_xfade_offsets_keep_both_cards_visible():
    # Each xfade must be placed at (first-input length - CARD_FADE) so the
    # second segment fully follows. This guards the tail offset, which the
    # topology-only connectivity check cannot catch: too large an offset pushes
    # the crossfade past [ihead]'s EOF and the outro card silently drops out.
    for plan in (
        _two_scene_plan("crossfade"),
        _two_scene_plan("cut"),
        _single_scene_plan(),
    ):
        w, h = resolution_size(plan)
        style = get_style_config(plan.get("style"))
        _, _, body_dur = build_filtergraph(plan["scenes"], w, h, style)
        graph = _graph(plan)

        # Head: [intro] (CARD_DURATION long) crossfades into the body.
        head = re.search(
            r"\[intro\]\[[^\]]+\]xfade=transition=fade:"
            r"duration=([0-9.]+):offset=([0-9.]+)\[ihead\]",
            graph,
        )
        assert head is not None
        h_dur, h_off = float(head.group(1)), float(head.group(2))
        assert abs(h_off - (CARD_DURATION - h_dur)) < 1e-6

        # [ihead] length after the head crossfade overlap.
        ihead_len = (CARD_DURATION - CARD_FADE) + body_dur

        # Tail: [ihead] crossfades into [outro]. The window must fit inside
        # [ihead] and be placed at (len - duration) so the outro fully follows.
        tail = re.search(
            r"\[ihead\]\[outro\]xfade=transition=fade:"
            r"duration=([0-9.]+):offset=([0-9.]+)\[vout\]",
            graph,
        )
        assert tail is not None
        t_dur, t_off = float(tail.group(1)), float(tail.group(2))
        assert t_off + t_dur <= ihead_len + 1e-6, "outro window past [ihead] EOF"
        assert abs(t_off - (ihead_len - t_dur)) < 1e-6
