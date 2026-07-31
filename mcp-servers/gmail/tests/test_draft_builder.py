"""Offline unit tests for the Gmail draft MIME builder. No network, no env."""
import base64
import importlib.util
import pathlib
from email import message_from_bytes

import pytest

BUILDER_PATH = pathlib.Path(__file__).resolve().parents[1] / "draft_builder.py"


def _load():
    spec = importlib.util.spec_from_file_location("draft_builder", BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _decode(raw: str):
    # Gmail uses base64url; email libs need standard padding handling.
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_builds_headers_and_body(mod):
    raw = mod.build_draft_raw("a@b.com", "Hi there", "Hello body")
    msg = _decode(raw)
    assert msg["To"] == "a@b.com"
    assert msg["Subject"] == "Hi there"
    assert "Hello body" in msg.get_payload(decode=True).decode("utf-8")


def test_includes_cc_and_bcc_when_given(mod):
    raw = mod.build_draft_raw("a@b.com", "s", "b", cc="c@d.com", bcc="e@f.com")
    msg = _decode(raw)
    assert msg["Cc"] == "c@d.com"
    assert msg["Bcc"] == "e@f.com"


def test_omits_cc_bcc_when_absent(mod):
    raw = mod.build_draft_raw("a@b.com", "s", "b")
    msg = _decode(raw)
    assert msg["Cc"] is None
    assert msg["Bcc"] is None


def test_empty_recipient_raises(mod):
    with pytest.raises(ValueError):
        mod.build_draft_raw("   ", "s", "b")
    with pytest.raises(ValueError):
        mod.build_draft_raw("", "s", "b")


def test_subject_with_crlf_raises(mod):
    with pytest.raises(ValueError):
        mod.build_draft_raw("a@b.com", "Hi\r\nBcc: evil@x.com", "b")


def test_to_with_newline_raises(mod):
    with pytest.raises(ValueError):
        mod.build_draft_raw("a@b.com\nBcc: evil@x.com", "s", "b")


def test_body_with_newline_is_allowed(mod):
    raw = mod.build_draft_raw("a@b.com", "s", "line one\nline two")
    msg = _decode(raw)
    assert "line one\nline two" in msg.get_payload(decode=True).decode("utf-8")


# --- draft with a real file attachment ----------------------------------------

def test_attachment_draft_builds_multipart(mod):
    payload = b"%PDF-\x00\x01binary"
    raw = mod.build_draft_raw_with_attachment(
        "a@b.com", "Report attached", "Here is the file.",
        "report.pdf", base64.b64encode(payload).decode(), "application/pdf")
    msg = _decode(raw)
    assert msg.is_multipart()
    assert msg["To"] == "a@b.com"
    assert msg["Subject"] == "Report attached"
    parts = list(msg.walk())
    texts = [p for p in parts if p.get_content_type() == "text/plain"]
    assert any("Here is the file." in p.get_payload() for p in texts)
    atts = [p for p in parts if p.get_filename() == "report.pdf"]
    assert len(atts) == 1
    assert atts[0].get_payload(decode=True) == payload
    assert atts[0].get_content_type() == "application/pdf"


def test_attachment_draft_requires_recipient(mod):
    with pytest.raises(ValueError):
        mod.build_draft_raw_with_attachment(
            "", "s", "b", "f.pdf", base64.b64encode(b"x").decode(), "application/pdf")


def test_attachment_draft_rejects_bad_base64(mod):
    with pytest.raises(ValueError):
        mod.build_draft_raw_with_attachment(
            "a@b.com", "s", "b", "f.pdf", "!!!not-base64!!!", "application/pdf")
