import pytest
from video_refine import (
    REFINE_SCHEMA, build_system_prompt, build_messages,
    append_turn, keep_only_latest_proposal_plan, latest_pending_proposal,
    mark_proposal_applied,
)

PLAN = {"template_id": "product_demo", "title": "t",
        "scenes": [{"screenshot": "screenshot-1.png", "caption": "c",
                    "duration_s": 3, "transition": "cut"}],
        "narration_script": "hi"}

def test_schema_allows_ask_and_propose():
    assert REFINE_SCHEMA["properties"]["action"]["enum"] == ["ask", "propose"]
    assert "plan" in REFINE_SCHEMA["properties"]

def test_system_prompt_lists_screenshots_and_plan():
    sp = build_system_prompt(PLAN, ["screenshot-1.png", "screenshot-2.png"])
    assert "screenshot-2.png" in sp and "narration_script" in sp

def test_build_messages_caps_to_40_turns():
    convo = [{"role": "user", "kind": "message", "content": str(i)} for i in range(60)]
    msgs = build_messages(convo, "newest")
    assert len(msgs) <= 41
    assert msgs[-1]["content"] == "newest"

def test_keep_only_latest_proposal_plan_strips_old_plans():
    convo = [
        {"role": "assistant", "kind": "proposal", "content": "v1", "plan": PLAN, "applied": True},
        {"role": "assistant", "kind": "proposal", "content": "v2", "plan": PLAN, "applied": False},
    ]
    out = keep_only_latest_proposal_plan(convo)
    assert "plan" not in out[0]
    assert out[1]["plan"] == PLAN

def test_latest_pending_proposal_and_mark_applied():
    convo = [
        {"role": "assistant", "kind": "proposal", "content": "old", "plan": PLAN, "applied": True},
        {"role": "assistant", "kind": "proposal", "content": "new", "plan": PLAN, "applied": False},
    ]
    p = latest_pending_proposal(convo)
    assert p["content"] == "new"
    out = mark_proposal_applied(convo, p)
    assert latest_pending_proposal(out) is None
