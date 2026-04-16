from claude_executor import build_prompt, parse_outcome


def test_build_prompt_includes_task_fields():
    p = build_prompt(
        description="Fix routing",
        action_type="BUILD",
        priority="CRITICAL",
        meeting_title="Standup",
        meeting_date="Apr 8",
    )
    assert "Fix routing" in p and "BUILD" in p and "CRITICAL" in p and "Standup" in p


def test_parse_completed():
    o = parse_outcome("Did the work.\nCOMPLETED: Updated Caddyfile and reloaded.")
    assert o.kind == "completed"
    assert o.payload == "Updated Caddyfile and reloaded."


def test_parse_needs_input():
    o = parse_outcome("Looked at it.\nNEEDS_INPUT: What's the Trello API token?")
    assert o.kind == "needs_input"
    assert "Trello API token" in o.payload


def test_parse_needs_steps():
    o = parse_outcome("NEEDS_STEPS: 1. Open Caddyfile\n2. Edit\n3. Reload")
    assert o.kind == "needs_steps"
    assert o.payload.startswith("1. Open Caddyfile")


def test_parse_no_sentinel_treated_as_failed():
    o = parse_outcome("I tried but I'm confused.")
    assert o.kind == "failed"
