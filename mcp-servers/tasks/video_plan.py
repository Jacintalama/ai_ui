"""AI scripting: generate and validate a schema-constrained slideshow video plan.

`validate_plan` is a pure function (offline). `generate_plan` calls the Claude
API with structured outputs (model `claude-opus-4-8`) to produce a plan, then
validates it against the available screenshots.
"""
import json
import os

import anthropic

TEMPLATES = {"product_demo", "feature_walkthrough"}
MAX_TOTAL_SECONDS = 60
# Per-scene duration bounds (seconds). These mirror the inline limits that
# validate_plan enforces; clamp_plan uses them to coerce model output into range.
MIN_SCENE_SECONDS = 0.5
MAX_SCENE_SECONDS = 15.0


class PlanInvalid(Exception):
    pass


PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "template_id": {"type": "string"},
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
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
        "resolution": {"type": "string", "enum": ["720p", "1080p"]},
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


async def generate_plan(prompt: str, screenshots: list[str]) -> dict:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    sys = (
        "You produce a JSON plan for a short narrated slideshow video built from the "
        "given screenshots. Use ONLY the provided screenshot filenames. Keep total "
        f"duration under {MAX_TOTAL_SECONDS}s. Templates: {sorted(TEMPLATES)}."
    )
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
