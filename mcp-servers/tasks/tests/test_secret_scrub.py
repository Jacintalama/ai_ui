"""Tests for secret_scrub — credential redaction patterns."""
import os
import sys

# Make the tasks/ dir importable when running tests directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from secret_scrub import scrub

# NOTE: fake credential bodies are assembled at runtime (prefix + body) so the
# literal token strings never appear in source. This avoids secret-scanner
# false positives while still exercising the scrubber's regexes once joined.


def test_anthropic_key_redacted():
    txt = f'key={"sk-ant-" + "abcDEF12345xyz67890extrakey"} and tail'
    out = scrub(txt)
    assert "sk-ant-abc" not in out
    assert "<REDACTED_ANTHROPIC>" in out
    assert "tail" in out  # surrounding text preserved


def test_jwt_three_segments_redacted():
    jwt = "eyJabc123_def" + ".eyJpayload456ghi" + ".signaturepart789xyz"
    txt = f"Bearer {jwt} more"
    out = scrub(txt)
    assert "eyJabc" not in out
    assert "<REDACTED_JWT>" in out


def test_two_segment_string_not_redacted():
    # Looks like part of a JWT but isn't full — leave alone
    txt = "eyJabc123.eyJdef456"
    assert scrub(txt) == txt


def test_safe_prefix_alone_not_redacted():
    txt = "doc says use prefix sk-ant- when sharing"
    # "sk-ant-" alone (no key body) shouldn't trigger
    assert scrub(txt) == txt


def test_idempotent():
    txt = f'key={"sk-ant-" + "realkey12345abcdefxyzmore"}'
    once = scrub(txt)
    twice = scrub(once)
    assert once == twice


def test_google_key():
    txt = f'GOOGLE_API_KEY={"AIza" + "SyDfakekeypayload1234567890abcdef"}'
    out = scrub(txt)
    assert "AIza" not in out or "<REDACTED_GOOGLE>" in out


def test_duffel_key():
    txt = f'DUFFEL_API_KEY={"duffel_test_" + "abcDEF1234567890realtoken"}'
    out = scrub(txt)
    assert "duffel_test_abc" not in out
    assert "<REDACTED_DUFFEL>" in out


def test_github_token():
    txt = f'GITHUB_TOKEN={"ghp_" + "abcDEF1234567890realtokenpayloadxyz123"}'
    out = scrub(txt)
    assert "<REDACTED_GITHUB>" in out


def test_slack_bot_token():
    txt = f'x={"xoxb-" + "1234567890-abcDEF1234567890realtoken-xyz"}'
    out = scrub(txt)
    assert "<REDACTED_SLACK>" in out
