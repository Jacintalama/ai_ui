"""Discord App Builder build/enhance can carry extracted attachment text.

The Discord bot extracts a PDF/Word/text attachment and passes its text via new
optional attachment_text/attachment_name fields; the build/enhance prompt
includes it, framed as untrusted data. Web JSON callers omit the fields
(backward compatible). (2026-06-18.)
"""
import base64
import os

os.environ.setdefault("AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("DATABASE_URL", "postgresql://t:t@localhost/test")

from routes_aiuibuilder import BuildRequest, EnhanceRequest, _attachment_block  # noqa: E402


def test_build_request_accepts_optional_attachment_fields():
    r = BuildRequest(description="a cafe site", attachment_text="menu text",
                     attachment_name="menu.pdf")
    assert r.attachment_text == "menu text"
    assert r.attachment_name == "menu.pdf"
    # backward compatible: omitting them is fine (web JSON callers)
    bare = BuildRequest(description="a cafe site")
    assert bare.attachment_text is None and bare.attachment_name is None


def test_enhance_request_accepts_optional_attachment_fields():
    r = EnhanceRequest(prompt="match this", attachment_text="spec body",
                       attachment_name="spec.docx")
    assert r.attachment_text == "spec body"
    bare = EnhanceRequest(prompt="match this")
    assert bare.attachment_text is None


def test_attachment_block_frames_untrusted_and_includes_text():
    b = _attachment_block("spec.pdf", "the full spec body")
    assert "spec.pdf" in b
    assert "the full spec body" in b
    assert "untrusted" in b.lower()


def test_attachment_block_empty_when_no_text():
    assert _attachment_block("x.pdf", "") == ""
    assert _attachment_block("x.pdf", None) == ""
    assert _attachment_block(None, "body") != ""  # name optional, text present
