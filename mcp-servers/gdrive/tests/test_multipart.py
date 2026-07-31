"""Multipart body builder: must handle binary payloads byte-exactly."""
import os
import sys

# main requires a Fernet key at import; any well-formed key works for this
# pure-function test (32 zero bytes, urlsafe-b64). Never a real secret.
os.environ.setdefault("AIUI_FERNET_KEY",
                      "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from main import build_multipart  # noqa: E402


def test_build_multipart_binary_payload_intact():
    payload = b"%PDF-\x00\x01\xffbinary"
    body = build_multipart("a.pdf", "application/pdf", payload, "BND")
    assert payload in body                      # bytes not mangled
    assert b'{"name": "a.pdf"}' in body
    assert body.startswith(b"--BND\r\n")
    assert body.endswith(b"--BND--")
    assert b"Content-Type: application/pdf" in body
