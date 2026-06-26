"""Orchestrator: render a video job via the remotion service, mux audio locally."""
import asyncio
import json as _json
import os

from video_remotion_client import render_remotion
from video_anim import _synthesize_narration, _build_audio_mux_args
from video_plan import DEFAULT_ANIMATION_PRESET, ensure_anim_narration


async def _run_audio_mux(video_in: str, out_path: str, audio_path: str | None) -> str:
    """Run ffmpeg to mux narration + ambient bed onto video_in, writing out_path.

    audio_path is positional (not keyword-only) so tests can monkeypatch this
    function and call it positionally: fake_mux(video_in, out_path, audio_path).
    """
    args = _build_audio_mux_args(video_in, out_path, audio_path=audio_path)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode(errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg audio mux failed (exit {proc.returncode}): {tail}")
    return out_path


async def render_remotion_job(
    apps_dir: str,
    slug: str,
    job_id: str,
    plan: dict,
    *,
    fps: int = 24,
    voice: str | None = None,
    animation_preset: str = DEFAULT_ANIMATION_PRESET,
) -> str:
    """Render a video job via the remotion service and mux audio locally.

    Returns the path to the final out.mp4.
    """
    job_dir = os.path.join(apps_dir, slug, ".video", job_id)

    # Load site context (host, title) - best-effort, default to empty strings.
    ctx_path = os.path.join(job_dir, "site_context.json")
    ctx: dict = {}
    if os.path.isfile(ctx_path):
        try:
            with open(ctx_path, encoding="utf-8") as f:
                ctx = _json.load(f)
        except Exception:  # noqa: BLE001 - context is best-effort
            ctx = {}
    host = str(ctx.get("host") or "")
    title = str(ctx.get("title") or "")
    plan = ensure_anim_narration(plan, "")

    # Build scene list for the remotion service, converting duration_s -> durationS
    # and resolving screenshot filenames to absolute paths.
    scenes: list[dict] = []
    for sc in plan.get("scenes") or []:
        screenshot_file = sc.get("screenshot")
        if screenshot_file:
            screenshot_abs: str | None = os.path.join(job_dir, "screenshots", screenshot_file)
        else:
            screenshot_abs = None
        scenes.append({
            "kind": sc.get("kind", "screenshot"),
            "screenshot": screenshot_abs,
            "headline": str(sc.get("headline") or ""),
            "subtext": str(sc.get("subtext") or ""),
            "motion": sc.get("motion", "fade"),
            "durationS": float(sc.get("duration_s") or 3.0),
        })

    # Synthesize narration via Piper (returns None if unavailable).
    narration = await _synthesize_narration(
        plan.get("narration_script") or "",
        voice,
        os.path.join(job_dir, "narration.wav"),
    )

    # Render video-only via remotion service.
    video_only = await render_remotion(
        job_dir,
        theme="parity",
        fps=fps,
        width=1280,
        height=720,
        host=host,
        title=title,
        scenes=scenes,
        animationPreset=animation_preset,
    )

    # Mux ambient bed + optional narration onto the video.
    out = os.path.join(job_dir, "out.mp4")
    await _run_audio_mux(video_only, out, narration)
    return out
