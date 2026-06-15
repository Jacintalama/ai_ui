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
                    "duration_s": {"type": "number"},
                    "transition": {"type": "string", "enum": ["crossfade", "cut"]},
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
    validate_plan(plan, screenshots)
    return plan
