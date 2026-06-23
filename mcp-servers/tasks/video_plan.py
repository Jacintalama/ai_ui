"""AI scripting: generate and validate a schema-constrained slideshow video plan.

`validate_plan` is a pure function (offline). `generate_plan` calls the Claude
API with structured outputs (model `claude-opus-4-8`) to produce a plan, then
validates it against the available screenshots.
"""
import json
import logging
import os

import anthropic

logger = logging.getLogger("video_plan")

TEMPLATES = {"product_demo", "feature_walkthrough"}
MAX_TOTAL_SECONDS = 60
# Per-scene duration bounds (seconds). These mirror the inline limits that
# validate_plan enforces; clamp_plan uses them to coerce model output into range.
MIN_SCENE_SECONDS = 0.5
MAX_SCENE_SECONDS = 15.0


class PlanInvalid(Exception):
    pass


# Engine-appropriate "skills" for the narrated screenshot-slideshow generator
# (ffmpeg + Piper, NOT Remotion). Baked into the generate AND refine prompts so
# every video follows them. Mirrors the App Builder's build_rules() pattern of
# injecting domain guidance into the system prompt.
VIDEO_BEST_PRACTICES = (
    "NARRATED-SLIDESHOW BEST PRACTICES — follow these for every plan:\n"
    "- Structure: open with a strong HOOK scene (what it is / why care), then a "
    "logical arc (context -> key features or benefits -> a short wrap-up/CTA). "
    "Group related screenshots; you need NOT use every screenshot — pick the ones "
    "that best tell the story.\n"
    "- Narration: conversational and benefit-led, ONE idea per scene, ~1-2 short "
    "sentences. Don't read the UI verbatim or list every element — say why it "
    "matters. Active voice. A scene's narration must be speakable within its "
    "duration (~2.5 words/second), so size duration_s to the narration (and "
    "vice-versa).\n"
    "- Captions: SHORT on-screen labels (<= ~6 words), punchy, COMPLEMENTING the "
    "narration rather than repeating it. Sentence fragments, not paragraphs.\n"
    "- Pacing: most scenes 2.5-5s — long enough to read the caption and hear the "
    "narration, short enough to stay snappy; avoid a run of sub-2s scenes. Keep "
    "the whole video tight (well under 60s; 20-45s is ideal).\n"
    "- Transitions: use 'crossfade'/'dissolve' between related scenes for flow, "
    "'cut' for a deliberate snap, 'section' to mark a new topic — don't overuse "
    "any one.\n"
    "- Reference ONLY the provided screenshot filenames, exactly as given."
)


def build_plan_system_prompt() -> str:
    """System prompt for initial plan generation (testable, skill-injected)."""
    return (
        "You produce a JSON plan for a short narrated slideshow video built from the "
        "given screenshots. Use ONLY the provided screenshot filenames. Keep total "
        f"duration under {MAX_TOTAL_SECONDS}s. Templates: {sorted(TEMPLATES)}.\n\n"
        + VIDEO_BEST_PRACTICES
    )


PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "template_id": {"type": "string"},
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "screenshot": {"type": "string"},
                    "caption": {"type": "string"},
                    "narration": {"type": "string"},
                    "duration_s": {"type": "number"},
                    "transition": {
                        "type": "string",
                        "enum": ["crossfade", "cut", "dissolve", "next", "section"],
                    },
                },
                "required": ["screenshot", "caption", "duration_s", "transition"],
            },
        },
        "narration_script": {"type": "string"},
        "resolution": {"type": "string", "enum": ["720p"]},
    },
    "required": ["template_id", "title", "scenes", "narration_script"],
}


def validate_plan(plan: dict, available: list[str]) -> None:
    if plan.get("template_id") not in TEMPLATES:
        raise PlanInvalid(f"unknown template_id {plan.get('template_id')!r}")
    scenes = plan.get("scenes") or []
    if not scenes:
        raise PlanInvalid("plan has no scenes")
    have = set(available)
    total = 0.0
    for sc in scenes:
        if sc["screenshot"] not in have:
            raise PlanInvalid(f"scene references missing screenshot {sc['screenshot']!r}")
        if not (0.5 <= float(sc["duration_s"]) <= 15):
            raise PlanInvalid("scene duration out of range")
        total += float(sc["duration_s"])
    if total > MAX_TOTAL_SECONDS:
        raise PlanInvalid(f"video too long ({total}s > {MAX_TOTAL_SECONDS}s)")


def clamp_plan(plan: dict) -> dict:
    """Coerce scene durations into the range validate_plan enforces.

    The model occasionally returns an over-long scene (e.g. one screenshot +
    a long narration) or a total over the cap, which would make validate_plan
    reject the plan and fail the render. This clamps each scene's duration into
    [MIN_SCENE_SECONDS, MAX_SCENE_SECONDS] and, if the total still exceeds
    MAX_TOTAL_SECONDS, scales every scene down proportionally (re-clamping to
    the per-scene minimum). Mutates and returns the same plan dict for chaining.

    Defensive: if ``plan`` is not a dict or has no ``scenes`` list it is
    returned unchanged so validate_plan still performs the real rejection.
    """
    if not isinstance(plan, dict):
        return plan
    # Cap resolution to 720p. The ~3.8GB render box OOMs on 1080p (the eased
    # 2x-supersample motion + color grade peak at the full box), while every
    # style renders comfortably at 720p (benchmarked). Coerce here so old or
    # refined plans that still carry 1080p can never reach the renderer.
    if plan.get("resolution") != "720p":
        plan["resolution"] = "720p"
    scenes = plan.get("scenes")
    if not isinstance(scenes, list):
        return plan

    for sc in scenes:
        if not isinstance(sc, dict):
            continue
        try:
            dur = float(sc.get("duration_s"))
        except (TypeError, ValueError):
            dur = 3.0
        if dur != dur:  # NaN guard
            dur = 3.0
        sc["duration_s"] = max(MIN_SCENE_SECONDS, min(MAX_SCENE_SECONDS, dur))

    sized = [sc for sc in scenes if isinstance(sc, dict) and "duration_s" in sc]
    total = sum(float(sc["duration_s"]) for sc in sized)
    if total > MAX_TOTAL_SECONDS and total > 0:
        scale = MAX_TOTAL_SECONDS / total
        for sc in sized:
            scaled = max(MIN_SCENE_SECONDS, float(sc["duration_s"]) * scale)
            sc["duration_s"] = round(scaled, 2)

    # Proportional scaling re-clamps any shrunk scene back up to the per-scene
    # floor, so the total can land back over the cap (e.g. many tiny scenes
    # that all floor-bump to MIN_SCENE_SECONDS). Trim the longest scene by the
    # overflow, never below the floor, until the total fits or every scene is
    # already at the floor.
    def _total() -> float:
        return sum(float(sc["duration_s"]) for sc in sized)

    for _ in range(len(sized) + 1):
        overflow = _total() - MAX_TOTAL_SECONDS
        if overflow <= 0:
            break
        longest = max(sized, key=lambda sc: float(sc["duration_s"]))
        headroom = float(longest["duration_s"]) - MIN_SCENE_SECONDS
        if headroom <= 0:
            break  # every scene already at the per-scene floor
        new_dur = round(float(longest["duration_s"]) - min(overflow, headroom), 2)
        if new_dur >= float(longest["duration_s"]):
            break  # rounding stalled progress; avoid an infinite loop
        longest["duration_s"] = new_dur

    # Last resort: more scenes than can fit even at the per-scene floor. Such a
    # plan is infeasible and validate_plan will still reject it, but clamp_plan
    # must never return a total above the hard cap, so scale below the floor.
    # This branch intentionally trades the 0.5s floor for the <=60 cap, so validate_plan then rejects the (infeasible) plan on its per-scene duration check.
    total = _total()
    if total > MAX_TOTAL_SECONDS and total > 0:
        scale = MAX_TOTAL_SECONDS / total
        for sc in sized:
            sc["duration_s"] = round(float(sc["duration_s"]) * scale, 2)

    return plan


def _fallback_plan(prompt: str, screenshots: list[str]) -> dict:
    """Deterministic, always-valid plan used when the model fails to return a
    usable plan (e.g. an empty `scenes` array). One scene per screenshot (capped
    so the total fits MAX_TOTAL_SECONDS) guarantees a video still renders rather
    than failing with 'plan has no scenes'. Narration carries the user's prompt
    on the opening scene; the slideshow itself does the rest."""
    shots = list(screenshots[:12]) or list(screenshots)
    n = max(1, len(shots))
    per = max(MIN_SCENE_SECONDS, min(5.0, round(MAX_TOTAL_SECONDS / n, 2)))
    clean = (prompt or "").strip()
    scenes = [
        {
            "screenshot": s,
            "caption": "",
            "narration": clean if i == 0 else "",
            "duration_s": per,
            "transition": "crossfade",
        }
        for i, s in enumerate(shots)
    ]
    return {
        "template_id": "feature_walkthrough",
        "title": (clean[:60] or "Walkthrough"),
        "scenes": scenes,
        "narration_script": clean,
        "resolution": "720p",
    }


async def generate_plan(prompt: str, screenshots: list[str], *, attempts: int = 3) -> dict:
    """Generate a slideshow plan from the prompt + screenshots, resiliently.

    The model occasionally returns a schema-valid-but-empty plan (no scenes) or a
    transient API error; a single bad response must not fail the whole video. So
    we retry up to `attempts` times and, if every attempt fails, fall back to a
    deterministic one-scene-per-screenshot plan (when screenshots exist)."""
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    sys = build_plan_system_prompt()
    last_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            msg = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=2048,
                system=sys,
                output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
                messages=[
                    {"role": "user", "content": f"Prompt: {prompt}\nScreenshots: {screenshots}"}
                ],
            )
            text = next(b.text for b in msg.content if b.type == "text")
            plan = json.loads(text)
            clamp_plan(plan)
            validate_plan(plan, screenshots)
            return plan
        except Exception as e:  # noqa: BLE001 - retry on bad plan / API hiccup
            last_err = e
            logger.warning("generate_plan attempt %d/%d failed: %s: %s",
                           i + 1, attempts, type(e).__name__, e)
    if screenshots:
        logger.warning("generate_plan falling back to a deterministic plan after "
                       "%d attempts (last error: %s)", attempts, last_err)
        plan = _fallback_plan(prompt, screenshots)
        clamp_plan(plan)
        validate_plan(plan, screenshots)  # valid by construction
        return plan
    raise PlanInvalid(f"could not generate a plan: {last_err}")
