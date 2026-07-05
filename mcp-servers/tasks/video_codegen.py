"""Piece C: AI-authored Remotion composition codegen, run in the tasks service.

tasks holds the ANTHROPIC_API_KEY and does NOT execute the generated code; it calls
Claude to author a single-file composition, then hands the source to the
video-remotion sandbox (POST /render-ai) which compiles + renders it under the Piece B
guards. On a gate failure the error is fed back and we regenerate (repair loop).

Heavy deps (anthropic, video_plan, video_vision, narration/mux) are imported lazily so
this module stays cheap to import and the pure logic is unit-testable without them.
"""
import logging
import os
import re

logger = logging.getLogger("video_codegen")

# Vendored copy of the LOCKED correctness contract. tasks is a separate image from
# video-remotion, so it carries its own prompt copy; the real ENFORCEMENT is the
# sandbox bundler import-guard + caps in video-remotion, regardless of this text.
CONTRACT = """# Remotion composition — correctness contract (LOCKED)

You write ONE self-contained Remotion composition (TypeScript + JSX) from a short brief.
If any rule is broken the video will not render.

## Output
Return exactly one fenced ```tsx code block — the whole composition. No prose, no second file.

## Structure (required)
- Import ONLY from "remotion", "@remotion/*", "react". Nothing else.
- Define your component(s).
- export const Root: React.FC = () => (<Composition id="Video" component={Main} durationInFrames={<NUMBER LITERAL>} fps={30} width={1280} height={720} />);
- Call registerRoot(Root); at the very end.
- durationInFrames is a numeric literal. No calculateMetadata, no required props, no defaultProps.

## Determinism (a Remotion video is a pure function of the frame)
- Drive ALL motion from useCurrentFrame(); read fps via useVideoConfig().
- FORBIDDEN: Math.random(), Date.now(), new Date(), crypto randomness, performance.now() — use random("seed") from remotion.
- FORBIDDEN: useState, useEffect, setTimeout, setInterval, requestAnimationFrame, dynamic import(), require().
- FORBIDDEN: CSS transition/animation/@keyframes/Tailwind animate-*; fetch/network/file I/O; imports outside the allow-list.
- Every interpolate inputRange MUST be strictly increasing (e.g. [0, 30, 60], never [0, 32, 13]).
- Math.sin/cos/PI/min/max are fine; only Math.random is banned.

## Assets
- Embed images ONLY with <Img src={staticFile("exact-name.png")} /> using ONLY the exact filenames provided. If none are provided, use no assets.

## Fonts
- These system font families are installed in the renderer and usable via the CSS fontFamily property: "Inter", "Roboto", "Open Sans", "Lato", "Bebas Neue", "EB Garamond", "Cantarell", "JetBrains Mono", "Fira Code".
- Use ONLY those families (plus generic sans-serif/serif/monospace fallbacks). No @font-face, no font downloads, no other families - anything else silently falls back.
- If the brief names one of these fonts, it is BINDING - use it for all display text.
"""


def ai_codegen_enabled() -> bool:
    """Feature flag for the AI-writes-the-video path. OFF by default; the template
    path stays the default until this is explicitly enabled (env AI_VIDEO_CODEGEN)."""
    return os.environ.get("AI_VIDEO_CODEGEN", "").strip().lower() in ("1", "true", "yes", "on")


async def render_remotion_or_ai(
    apps_dir: str,
    slug: str,
    job_id: str,
    plan: dict,
    prompt: str,
    *,
    voice: str | None = None,
    animation_preset: str = "cursor_click",
    screenshots: list[str] | None = None,
    screenshot_paths=None,
    site_context: dict | None = None,
    ai_enabled: bool | None = None,
    _ai_job=None,
    _template_job=None,
) -> str:
    """Dispatch the remotion render: AI-authored path when the flag is on, else the
    template path. The template path is ALWAYS the fallback — any AI-codegen failure
    is logged and we render the template so a member always gets a video."""
    if ai_enabled is None:
        ai_enabled = ai_codegen_enabled()
    if _template_job is None:
        from video_remotion_render import render_remotion_job as _template_job  # lazy

    if not ai_enabled:
        return await _template_job(apps_dir, slug, job_id, plan, voice=voice, animation_preset=animation_preset)

    if _ai_job is None:
        _ai_job = render_ai_job
    try:
        return await _ai_job(
            apps_dir, slug, job_id, prompt, plan,
            voice=voice, screenshots=screenshots, screenshot_paths=screenshot_paths, site_context=site_context,
        )
    except Exception:  # noqa: BLE001 - codegen must never deny a member their video
        logger.exception("AI codegen render failed for job %s; falling back to template path", job_id)
        return await _template_job(apps_dir, slug, job_id, plan, voice=voice, animation_preset=animation_preset)


def build_codegen_prompt(craft: str) -> str:
    """System prompt = LOCKED contract + EDITABLE craft (look/feel). Blank craft ->
    contract only. Mirrors the spike buildSystemPrompt."""
    craft = (craft or "").strip()
    return f"{CONTRACT.strip()}\n\n{craft}" if craft else CONTRACT.strip()


_FENCE = re.compile(r"```(?:tsx?|typescript|jsx?)?[^\n]*\n([\s\S]*?)```")


def extract_tsx(text: str) -> str:
    """Pull exactly one fenced code block (prefer the one with registerRoot). Falls
    back to raw text if it already looks like a composition; raises otherwise."""
    blocks = [m.group(1).strip() for m in _FENCE.finditer(text)]
    if not blocks:
        if re.search(r"registerRoot\s*\(", text):
            return text.strip()
        raise ValueError("model output had no code block")
    if len(blocks) > 1:
        for b in blocks:
            if re.search(r"registerRoot\s*\(", b):
                return b
        return blocks[-1]
    return blocks[0]


MAX_AI_VIDEO_S = 60.0  # matches the sandbox caps (MAX_FRAMES=1800 @ 30fps)
_SPEAK_WPS = 2.6  # approx speaking rate (words/sec) for sizing the script


def _target_seconds_from_brief(prompt: str, default: float = 30.0) -> float:
    """Requested duration from the brief ('explain for 30 secs' -> 30), default 30s,
    clamped to [8, MAX_AI_VIDEO_S]. Keeps videos near what the user asked for (and
    short enough to render on the box in time)."""
    m = re.search(r"(\d{1,3})\s*(?:s\b|secs?\b|seconds?\b)", (prompt or "").lower())
    secs = float(m.group(1)) if m else default
    return max(8.0, min(MAX_AI_VIDEO_S, secs))


def _trim_script_to_seconds(script: str, seconds: float, wps: float = _SPEAK_WPS) -> str:
    """Keep whole sentences up to ~seconds of speech so the narration (and the video
    sized to it) respect the requested duration. Returns the script unchanged when
    already within budget."""
    script = (script or "").strip()
    if not script:
        return script
    budget = max(1, int(seconds * wps))
    words = script.split()
    if len(words) <= budget:
        return script
    out: list[str] = []
    count = 0
    for sentence in re.split(r"(?<=[.!?])\s+", script):
        n = len(sentence.split())
        if out and count + n > budget:
            break
        out.append(sentence)
        count += n
    return " ".join(out) if out else " ".join(words[:budget])


def _audio_duration_s(wav_path: str | None) -> float:
    """Duration of a WAV file in seconds (0.0 if missing/unreadable). Used to size
    the video to the narration so the voice always finishes before the video ends."""
    if not wav_path:
        return 0.0
    try:
        import wave
        with wave.open(wav_path, "rb") as w:
            rate = w.getframerate() or 1
            return w.getnframes() / float(rate)
    except Exception:  # noqa: BLE001 - duration is best-effort
        return 0.0


async def generate_composition(
    prompt: str,
    screenshots: list[str],
    craft: str,
    *,
    screenshot_paths: list[tuple[str, str]] | None = None,
    site_context: dict | None = None,
    feedback: str | None = None,
    target_duration_s: float | None = None,
    client=None,
) -> str:
    """Call Claude to author one composition. system = contract + craft; screenshots
    sent as vision when available; repair feedback appended. Returns the TSX source."""
    import anthropic  # lazy

    client = client or anthropic.Anthropic()
    system = build_codegen_prompt(craft)

    use_vision = bool(screenshot_paths)
    if use_vision:
        try:
            from video_vision import build_vision_content
            from video_plan import _resolve_brief
            content = build_vision_content(screenshot_paths, site_context or {}, _resolve_brief(prompt))
        except Exception:  # noqa: BLE001 - never let content-build sink generation
            logger.warning("build_vision_content failed; using text prompt")
            content = f"Brief:\n{prompt}"
            use_vision = False
    else:
        content = f"Brief:\n{prompt}"

    extras: list[str] = []
    if target_duration_s and target_duration_s > 0:
        secs = round(target_duration_s, 1)
        extras.append(
            f"IMPORTANT: make the video about {secs} seconds long — set durationInFrames "
            f"to {round(secs * 30)} (fps=30) so the narration finishes before the video ends."
        )
    if feedback:
        extras.append(
            "Your previous attempt FAILED these checks. Fix them and return the "
            f"COMPLETE corrected single-file composition:\n{feedback}"
        )
    for ex in extras:
        if isinstance(content, str):
            content += "\n\n" + ex
        else:
            content = content + [{"type": "text", "text": ex}]

    kwargs: dict = dict(
        model=os.environ.get("AI_CODEGEN_MODEL", "claude-opus-4-8"),
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    if use_vision:
        kwargs["thinking"] = {"type": "adaptive"}
    msg = client.messages.create(**kwargs)
    text = next(b.text for b in msg.content if b.type == "text")
    return extract_tsx(text)


async def _codegen_loop(
    prompt: str,
    screenshots: list[str],
    screenshot_paths,
    site_context,
    craft: str,
    *,
    generate,
    render_client,
    job_dir: str,
    assets: list[str],
    max_attempts: int = 3,
    target_duration_s: float | None = None,
) -> str:
    """Generate -> render_client(/render-ai); on a gate failure feed the error back and
    regenerate. Returns the video-only mp4 path; raises after max_attempts."""
    feedback: str | None = None
    last = None
    for attempt in range(1, max_attempts + 1):
        source = await generate(
            prompt, screenshots, craft,
            screenshot_paths=screenshot_paths, site_context=site_context, feedback=feedback,
            target_duration_s=target_duration_s,
        )
        res = await render_client(job_dir, source, assets)
        if res.get("ok") and res.get("outPath"):
            logger.info("AI codegen succeeded on attempt %d/%d", attempt, max_attempts)
            return res["outPath"]
        feedback = res.get("error") or "render failed"
        last = res
        logger.warning(
            "AI codegen attempt %d/%d failed at %s: %s",
            attempt, max_attempts, res.get("stage"), str(feedback)[:300],
        )
    raise RuntimeError(f"AI codegen failed after {max_attempts} attempts: {str(last)[:300]}")


async def render_ai_job(
    apps_dir: str,
    slug: str,
    job_id: str,
    prompt: str,
    plan: dict,
    *,
    voice: str | None = None,
    screenshots: list[str] | None = None,
    screenshot_paths=None,
    site_context: dict | None = None,
    craft: str | None = None,
    max_attempts: int = 3,
    generate=None,
    render_client=None,
) -> str:
    """Full AI-path render: codegen loop -> video-only mp4 -> mux Piper narration
    (reusing the template path's narration synthesis + ffmpeg mux). Returns out.mp4.
    Narration text comes from the plan (Stage 1 still authors it), so we reuse it."""
    from video_plan import fetch_skill_best_practices, ensure_anim_narration
    from video_anim import _synthesize_narration
    from video_remotion_render import _run_audio_mux

    job_dir = os.path.join(apps_dir, slug, ".video", job_id)
    if craft is None:
        craft = await fetch_skill_best_practices() or ""
    if generate is None:
        generate = generate_composition
    if render_client is None:
        from video_remotion_client import render_ai as render_client  # lazy

    # 1) Narration FIRST so we can size the video to the voice. The mux uses
    #    -shortest (output = video length); if the video were shorter than the
    #    narration the voice got cut off. Sizing the video to narration + 1s tail
    #    means the voice always finishes, then the video ends.
    plan = ensure_anim_narration(plan or {}, prompt)
    # Respect the requested duration ("explain for 30 secs") — trim the narration to
    # that budget so the video is short enough to render on the box in time AND
    # matches what the user asked for.
    req_s = _target_seconds_from_brief(prompt)
    script = _trim_script_to_seconds(plan.get("narration_script") or "", req_s)
    narration = await _synthesize_narration(
        script,
        voice,
        os.path.join(job_dir, "narration.wav"),
    )
    narration_s = _audio_duration_s(narration)
    target_s = min(MAX_AI_VIDEO_S, narration_s + 1.0) if narration_s > 0 else req_s
    logger.info("AI video: narration %.1fs -> target video %s s", narration_s,
                round(target_s, 1) if target_s else "auto")

    # 2) Generate + render, EMBEDDING the captured screenshots (staged into the
    #    sandbox public/ by /render-ai) and sized to the narration.
    assets = list(screenshots or [])
    video_only = await _codegen_loop(
        prompt, assets, screenshot_paths, site_context, craft,
        generate=generate, render_client=render_client, job_dir=job_dir, assets=assets,
        max_attempts=max_attempts, target_duration_s=target_s,
    )

    # 3) Mux the narration onto the (voice-length) video.
    out = os.path.join(job_dir, "out.mp4")
    await _run_audio_mux(video_only, out, narration)
    return out
