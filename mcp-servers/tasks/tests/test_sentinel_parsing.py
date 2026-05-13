"""_SENTINEL_RE recognizes FAILED as a first-class terminal sentinel."""
from claude_executor import parse_outcome


def test_failed_sentinel_is_first_class():
    """FAILED: <reason> is parsed as kind=failed with structured payload."""
    out = parse_outcome("FAILED: agent_unreachable")
    assert out.kind == "failed"
    assert out.payload == "agent_unreachable"


def test_failed_at_end_of_output():
    """Last sentinel wins, just like COMPLETED."""
    out = parse_outcome("some chatter\nFAILED: timeout\n")
    assert out.kind == "failed"
    assert out.payload == "timeout"


def test_completed_still_works():
    """Regression: existing COMPLETED parsing unchanged."""
    out = parse_outcome("COMPLETED: built apps/foo/")
    assert out.kind == "completed"
    assert out.payload == "built apps/foo/"


def test_needs_input_still_works():
    out = parse_outcome("NEEDS_INPUT: which currency?")
    assert out.kind == "needs_input"
    assert out.payload == "which currency?"


def test_needs_steps_still_works():
    out = parse_outcome("NEEDS_STEPS: requires database")
    assert out.kind == "needs_steps"
    assert out.payload == "requires database"


def test_no_sentinel_still_failed():
    """Output with no sentinel still maps to failed (existing behavior)."""
    out = parse_outcome("random output with no sentinel here")
    assert out.kind == "failed"
    # payload is the trimmed text (last-500-char fallback)
    assert "random output" in out.payload
