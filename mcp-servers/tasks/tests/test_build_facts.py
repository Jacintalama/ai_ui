"""What a build actually did, read back out of its own transcript.

Every build stores the Claude Code stream-json it produced in
tasks.executions.log: 281 of them, 20MB, back to 2026-04-28. The last line is
a `result` record carrying what it cost, why it stopped and which models
answered, and the body carries every file it wrote. None of it is surfaced
anywhere, which is how $44.16 went on building junk apps out of a request for
a daily quote without anybody noticing.

Deterministic on purpose. No model reads these; a regex over a known shape is
cheaper, and it cannot invent a number that was never there.
"""
import build_facts

# The real shape, trimmed from a production transcript (boxing-landing-page,
# 2026-09-23). Two models answered: Claude Code titles the session with Haiku
# and does the work with Sonnet, so a reader that takes the LAST costUSD it
# sees reports the Sonnet share and silently loses the rest.
RESULT_LINE = (
    '{"type":"result","subtype":"success","stop_reason":"end_turn",'
    '"session_id":"88ed10a1","total_cost_usd":0.1163485,'
    '"usage":{"input_tokens":10,"output_tokens":369},'
    '"modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":601,'
    '"outputTokens":12,"costUSD":0.000661,"contextWindow":200000},'
    '"claude-sonnet-4-5":{"inputTokens":10,"outputTokens":369,'
    '"costUSD":0.1156875,"contextWindow":200000}},'
    '"permission_denials":[],"terminal_reason":"completed",'
    '"fast_mode_state":"off","uuid":"8f2d39d6"}'
)

WROTE_INDEX = (
    '{"type":"assistant","message":{"content":[{"type":"tool_use",'
    '"name":"Write","input":{"file_path":'
    '"/agent/work/boxing-landing-page-a03c/apps/boxing-landing-page-a03c/'
    'index.html","content":"<!doctype html>"}}]}}'
)
EDITED_CSS = (
    '{"type":"assistant","message":{"content":[{"type":"tool_use",'
    '"name":"Edit","input":{"file_path":'
    '"/agent/work/boxing-landing-page-a03c/apps/boxing-landing-page-a03c/'
    'styles.css","old_string":"a","new_string":"b"}}]}}'
)

LOG = "[spawning claude subprocess…]\n" + WROTE_INDEX + "\n" + EDITED_CSS + "\n" + RESULT_LINE


def test_it_reads_what_the_build_cost():
    assert build_facts.facts_from(LOG)["cost_usd"] == 0.1163485


def test_the_cost_is_the_whole_build_not_one_models_share():
    """total_cost_usd, never the last costUSD in modelUsage. Haiku titles the
    session and Sonnet does the work, so taking the last one loses Haiku's
    share on every build. Measured across 281 real builds: 79.92 the right
    way against 75.30 the wrong way."""
    facts = build_facts.facts_from(LOG)
    assert facts["cost_usd"] != 0.1156875
    assert facts["cost_usd"] == 0.1163485


def test_it_names_the_files_the_build_touched():
    """Relative to the app, not the build host. The absolute path names a
    working directory nobody will ever look at."""
    assert build_facts.facts_from(LOG)["files"] == ["index.html", "styles.css"]


def test_a_file_written_then_edited_is_named_once():
    twice = LOG + "\n" + WROTE_INDEX
    assert build_facts.facts_from(twice)["files"].count("index.html") == 1


def test_it_reads_why_the_build_stopped():
    assert build_facts.facts_from(LOG)["terminal_reason"] == "completed"


def test_it_names_every_model_that_answered():
    assert build_facts.facts_from(LOG)["models"] == [
        "claude-haiku-4-5-20251001", "claude-sonnet-4-5"]


def test_a_transcript_with_no_result_line_costs_nothing_rather_than_raising():
    """A killed build has no result record. It still wrote files, and the
    caller must get those rather than an exception."""
    facts = build_facts.facts_from(WROTE_INDEX)
    assert facts["cost_usd"] is None
    assert facts["terminal_reason"] == ""
    assert facts["files"] == ["index.html"]


def test_rubbish_reads_as_nothing():
    """These logs are 20MB of machine output from five months of changing
    formats. Anything unparseable is an empty answer, never a crash."""
    for junk in ("", "not json at all", '{"type":"result"}', None):
        facts = build_facts.facts_from(junk)
        assert facts["cost_usd"] is None
        assert facts["files"] == []


def test_a_key_after_modelUsage_is_not_a_model():
    """Caught by running this over all 281 real transcripts, not by the
    fixtures above: `tool_input` came back as a model. Reading a fixed window
    of characters past "modelUsage":{ runs off the end of it and into
    whatever the line carries next, which differs by Claude Code release."""
    line = (
        '{"type":"result","total_cost_usd":1.0,'
        '"modelUsage":{"claude-sonnet-4-5":{"inputTokens":10,"costUSD":1.0}},'
        '"tool_input":{"file_path":"x"},"permission_denials":[],'
        '"terminal_reason":"completed"}'
    )
    assert build_facts.facts_from(line)["models"] == ["claude-sonnet-4-5"]


def test_every_model_is_still_found_when_two_answered():
    """The bound must not cost the second model, which is the whole reason
    the cost is read from total_cost_usd."""
    assert build_facts.facts_from(LOG)["models"] == [
        "claude-haiku-4-5-20251001", "claude-sonnet-4-5"]
