"""/files/generate: pure pieces. Route wiring is verified on the server."""
from datetime import datetime

from routes_files import MAX_MD_BYTES, MAX_OUT_BYTES, build_filename


def test_build_filename_sanitizes_and_stamps():
    ts = datetime(2026, 7, 31, 10, 5, 0)
    assert build_filename("Q3 Report: final!", "docx", now=ts) == \
        "Q3_Report__final__20260731_100500.docx"
    assert build_filename("x", "pdf", now=ts).endswith(".pdf")


def test_build_filename_empty_title_defaults():
    ts = datetime(2026, 7, 31, 10, 5, 0)
    assert build_filename("", "pdf", now=ts) == "document_20260731_100500.pdf"


def test_caps_are_spec_values():
    assert MAX_MD_BYTES == 200_000
    assert MAX_OUT_BYTES == 5_000_000
