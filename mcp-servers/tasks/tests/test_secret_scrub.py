"""Tests for secret_scrub — credential redaction patterns."""
import os
import sys

# Make the tasks/ dir importable when running tests directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from secret_scrub import scrub


def test_anthropic_key_redacted():
    txt = "key=sk-ant-abcDEF12345_xyz67890extra and tail"
    out = scrub(txt)
    assert "sk-ant-abc" not in out
    assert "<REDACTED_ANTHROPIC>" in out
    assert "tail" in out  # surrounding text preserved


def test_jwt_three_segments_redacted():
    jwt = "eyJabc123_def.eyJpayload456ghi.signaturepart789xyz"
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
    txt = "key=sk-ant-realkey12345abcdef_xyz_more"
    once = scrub(txt)
    twice = scrub(once)
    assert once == twice


def test_google_key():
    txt = "GOOGLE_API_KEY=AIzaSyD-fake_key_payload_1234567890abcdef"
    out = scrub(txt)
    assert "AIza" not in out or "<REDACTED_GOOGLE>" in out


def test_duffel_key():
    txt = "DUFFEL_API_KEY=duffel_test_abcDEF1234567890_realtoken"
    out = scrub(txt)
    assert "duffel_test_abc" not in out
    assert "<REDACTED_DUFFEL>" in out


def test_github_token():
    txt = "GITHUB_TOKEN=ghp_abcDEF1234567890realtokenpayload_xyz123"
    out = scrub(txt)
    assert "<REDACTED_GITHUB>" in out


def test_slack_bot_token():
    txt = "x=xoxb-EXAMPLE-FAKE-FAKE-PLACEHOLDER"
    out = scrub(txt)
    assert "<REDACTED_SLACK>" in out
