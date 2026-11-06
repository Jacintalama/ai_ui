"""No dash is used as punctuation in copy somebody reads.

A standing rule, not a style preference: an em-dash is one of the clearest
tells that text was written by a machine, and this is Ralph's product.

Swept 2026-11-06. Before that, preview.html had 55 in visible copy and
projects.html 19, including "Re-publish is automatic - every new build is
live immediately" and "Lowercase letters, digits, and hyphens (3-50
chars)". The build overlay's own copy went earlier the same day.

Two things this deliberately does NOT flag:

  * CODE AND HTML COMMENTS. 94 of them across these pages. A comment is
    not copy, nobody reads it in the UI, and rewriting all of them would
    be a large diff that protects nothing.

  * A LONE dash used as a placeholder, as in a table cell with no value
    yet or a disabled Rollback button. That is a UI marker, not writing,
    and changing it would alter what somebody sees for no reason. The
    rule catches dashes with a space beside them, which is the
    punctuation use, and ranges between digits.
"""
import os
import re

import pytest

EM, EN = "—", "–"
STATIC = os.path.join(os.path.dirname(__file__), "..", "static")

PAGES = sorted(f for f in os.listdir(STATIC) if f.endswith(".html"))

_RANGE = re.compile("[0-9][" + EM + EN + "][0-9]")
_COMMENT_START = ("//", "*", "/*", "#", "<!--")


def _copy_lines(path):
    """Every line that is not a comment, with its number."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out, in_block = [], False
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if "/*" in stripped and "*/" not in stripped:
            in_block = True
            continue
        was_in_block = in_block
        if "*/" in stripped:
            in_block = False
        if was_in_block or stripped.startswith(_COMMENT_START):
            continue
        out.append((n, line))
    return out


def test_there_are_pages_to_check():
    """A rule that silently checks nothing is worse than no rule."""
    assert len(PAGES) >= 6, PAGES
    assert "preview.html" in PAGES


@pytest.mark.parametrize("page", PAGES)
def test_no_dash_is_used_as_punctuation(page):
    found = []
    for n, line in _copy_lines(os.path.join(STATIC, page)):
        for dash in (EM, EN):
            if " " + dash in line or dash + " " in line:
                found.append("%s:%d: %s" % (page, n, line.strip()[:90]))
                break
    assert not found, (
        "a dash is used as punctuation in copy somebody reads:\n  "
        + "\n  ".join(found[:8]))


@pytest.mark.parametrize("page", PAGES)
def test_a_range_is_written_with_the_word_to(page):
    """2 to 40 characters, not 2-40. The en-dash is typographically
    correct for a range and still a dash."""
    found = ["%s:%d: %s" % (page, n, line.strip()[:90])
             for n, line in _copy_lines(os.path.join(STATIC, page))
             if _RANGE.search(line)]
    assert not found, "a range is written with a dash:\n  " + "\n  ".join(found)


def test_the_check_would_actually_catch_one():
    """Guards the two above. A bug in _copy_lines that skipped every line
    would leave them passing on anything."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.html")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("<p>Ready " + EM + " go now</p>\n"
                     "// a comment " + EM + " ignored\n"
                     "<span>" + EM + "</span>\n")
        lines = _copy_lines(bad)
        text = " ".join(line for _, line in lines)
        assert "a comment" not in text, "comments are not being skipped"
        assert "Ready" in text and "<span>" in text
        assert sum(1 for _, line in lines
                   if " " + EM in line or EM + " " in line) == 1, (
            "the punctuation check does not fire on prose, or fires on a "
            "lone placeholder")
