"""Chat-driven refinement of a video plan (structured plan-regeneration).

refine_plan() asks Claude for either a clarifying question or a complete,
schema-valid revised plan; the validated plan is what the worker re-renders.
"""
from __future__ import annotations

import asyncio
import json
import os

import anthropic

from video_plan import PLAN_SCHEMA, VIDEO_BEST_PRACTICES, clamp_plan, validate_plan

REFINE_MODEL = "claude-opus-4-8"
MAX_HISTORY_TURNS = 40

REFINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "message"],
    "properties": {
        "action": {"type": "string", "enum": ["ask", "propose"]},
        "message": {"type": "string"},
        "plan": PLAN_SCHEMA,
    },
}


class RefineUnavailable(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is not configured."""


def build_system_prompt(current_plan: dict, screenshots: list[str]) -> str:
    return (
        "You are editing an existing narrated screenshot-slideshow video. "
        "You will receive the current render plan (JSON) and the list of "
        "available screenshot filenames. The user describes a change in plain "
        "language (reorder, delete, re-caption, retime scenes, rewrite the "
        "narration, or add scenes that use available screenshots).\n\n"
        "Rules:\n"
        "- Only reference screenshots from the provided list.\n"
        "- Keep total scene duration <= 60 seconds; each scene 0.5-15s.\n"
        "- Change ONLY what the user asked; keep everything else identical.\n"
        "- If the request is genuinely ambiguous, set action='ask' with a "
        "brief clarifying question and omit 'plan'.\n"
        "- Otherwise set action='propose', put a one-line summary of the "
        "change in 'message', and return a COMPLETE revised 'plan' that "
        "conforms to the schema.\n"
        "- When you (re)write scenes, narration, captions, pacing or "
        "transitions, apply the best practices below.\n\n"
        + VIDEO_BEST_PRACTICES + "\n\n"
        f"Available screenshots: {json.dumps(screenshots)}\n"
        f"Current plan: {json.dumps(current_plan)}"
    )


def build_messages(conversation: list[dict], message: str) -> list[dict]:
    recent = conversation[-MAX_HISTORY_TURNS:]
    # The Messages API requires the first message to be from the user; a slice
    # of a long history can start on an assistant turn, so drop leading
    # non-user turns.
    while recent and recent[0].get("role") != "user":
        recent = recent[1:]
    msgs: list[dict] = []
    for turn in recent:
        role = "user" if turn.get("role") == "user" else "assistant"
        msgs.append({"role": role, "content": str(turn.get("content", ""))})
    if not msgs or msgs[-1]["content"] != message:
        msgs.append({"role": "user", "content": message})
    return msgs


def append_turn(conversation: list[dict], role: str, kind: str,
                content: str, **extra) -> list[dict]:
    turn = {"role": role, "kind": kind, "content": content}
    turn.update(extra)
    return [*conversation, turn]


def keep_only_latest_proposal_plan(conversation: list[dict]) -> list[dict]:
    last_idx = max(
        (i for i, t in enumerate(conversation) if t.get("kind") == "proposal"),
        default=-1,
    )
    out = []
    for i, t in enumerate(conversation):
        if t.get("kind") == "proposal" and i != last_idx and "plan" in t:
            t = {k: v for k, v in t.items() if k != "plan"}
        out.append(t)
    return out


def latest_pending_proposal(conversation: list[dict]) -> dict | None:
    for t in reversed(conversation):
        if t.get("kind") == "proposal" and not t.get("applied") and t.get("plan"):
            return t
    return None


def mark_proposal_applied(conversation: list[dict], proposal: dict) -> list[dict]:
    out = []
    for t in conversation:
        if t is proposal or (t.get("kind") == "proposal"
                             and t.get("content") == proposal.get("content")
                             and not t.get("applied")):
            t = {**t, "applied": True}
        out.append(t)
    return out


def _call_model(system: str, messages: list[dict]) -> dict:
    """Blocking Anthropic structured-output call. Mirrors video_plan.generate_plan.
    Isolated so tests can monkeypatch it. Returns the parsed JSON object."""
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    resp = client.messages.create(
        model=REFINE_MODEL,
        max_tokens=2048,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": REFINE_SCHEMA}},
        messages=messages,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text)


async def refine_plan(current_plan: dict, screenshots: list[str],
                      conversation: list[dict], message: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RefineUnavailable("ANTHROPIC_API_KEY not configured")
    system = build_system_prompt(current_plan, screenshots)
    messages = build_messages(conversation, message)
    # Transport/JSON-decode errors from _call_model intentionally propagate
    # (only invalid plans downgrade to an ask) so the caller surfaces real failures.
    raw = await asyncio.to_thread(_call_model, system, messages)

    if raw.get("action") == "propose":
        plan = clamp_plan(raw.get("plan"))
        try:
            validate_plan(plan, screenshots)
        except Exception as exc:  # noqa: BLE001 - any failure downgrades to a re-ask
            return {"action": "ask",
                    "message": f"I could not build a valid change ({exc}). "
                               "Can you rephrase?"}
        return {"action": "propose",
                "message": raw.get("message") or "Here is the change.",
                "plan": plan}
    return {"action": "ask",
            "message": raw.get("message") or "Could you clarify what to change?"}
