"""_SENTINEL_RE recognizes FAILED as a first-class terminal sentinel."""
import json

from claude_executor import parse_outcome, line_outcome


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


def test_bare_completed_at_end_of_text():
    """A bare COMPLETED as the last token — no trailing colon, period, or
    whitespace — is still recognized.

    Regression (polar-express / aurora-air e2e): the agent ended its message
    with `…2026-10-05.\\n\\nCOMPLETED`. _SENTINEL_RE required a `[:\\s.]`
    terminator AFTER the keyword, so a keyword with nothing after it did not
    match and the run was misparsed.
    """
    out = parse_outcome("rebranded the app and wired live data.\n\nCOMPLETED")
    assert out.kind == "completed"
    assert out.payload == ""


def test_line_outcome_decodes_result_event():
    """line_outcome() returns the parsed Outcome for claude's terminal
    `result` event and None for any other stream-json line — even when the
    sentinel is a bare COMPLETED preceded by an escaped newline."""
    result_line = json.dumps({
        "type": "result",
        "subtype": "success",
        "result": "rebranded the app.\n\nCOMPLETED",
    })
    out = line_outcome(result_line)
    assert out is not None and out.kind == "completed"

    # an assistant event is not the terminal signal
    assistant_line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "COMPLETED"}]},
    })
    assert line_outcome(assistant_line) is None

    # non-JSON / unrelated lines are ignored
    assert line_outcome("plain log chatter") is None
