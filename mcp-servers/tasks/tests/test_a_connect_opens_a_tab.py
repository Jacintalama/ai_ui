# -*- coding: utf-8 -*-
"""A connect opens a TAB, never a popup window.

Ralph, 2026-11-16: "can you open new tab instead of like that popup new
tab". The reason is not taste. A popup lands behind the window that opened
it or gets swallowed by the blocker, and on 2026-11-16 an Airtable approval
popup could not be found or clicked at all, which stalled a reconnect that
four deployed write tools were waiting on.

The rule is mechanical: `window.open(url, name, features)` makes a POPUP
when the features ask for a size, and a TAB when they do not. So the one
thing to assert is that no shipped page asks for a size.

The second test guards the trap in making that change. Three of these
flows learn that they finished by watching the window they opened: the
Connections card polls `win.closed` and listens for the callback page's
postMessage, and both Vercel flows poll `win.closed`. Passing 'noopener'
returns null instead of a handle and breaks all of that silently, while
looking like a tidy security improvement. A call whose result is kept must
therefore never pass it.

Structural rather than browser-driven on purpose: the claim is about every
window.open in the codebase, and a browser test reaches only the ones it
manages to click.
"""
import pathlib
import re

import pytest

#: Pages and scripts WE author. Nothing vendored, so every hit is ours to
#: answer for. integrations-ui.js lives in the gdrive service because that
#: is the container that serves it into Open WebUI.
ROOT = pathlib.Path(__file__).resolve().parents[2]
SHIPPED = (
    ROOT / "gdrive" / "integrations-ui.js",
    ROOT / "tasks" / "static" / "agents.html",
    ROOT / "tasks" / "static" / "preview.html",
    ROOT / "tasks" / "static" / "projects.html",
    ROOT / "tasks" / "static" / "templates.html",
)

#: Every window.open call, as (file, line, argument text). DOTALL and one
#: level of nested parens, because a call is sometimes written across two
#: lines and its URL is often built with encodeURIComponent(...).
CALL = re.compile(r"window\.open\(((?:[^()]|\([^()]*\))*)\)", re.S)

#: How many there are today, counted rather than guessed. The number may
#: move as pages change; a silent drop toward zero is what this catches,
#: because an empty scan passes every other assertion in this file.
AT_LEAST = 16


def _calls():
    """Matched against the WHOLE file, with the line derived from the
    offset. Scanning line by line found 15 of 16 and would have found 0
    after any reformat, which is the failure mode worth designing out."""
    found = []
    for path in SHIPPED:
        assert path.exists(), "shipped file moved: %s" % path
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in CALL.finditer(text):
            found.append((path.name, text[:m.start()].count("\n") + 1,
                          m.group(1)))
    return found


def _features(args: str) -> str:
    """The third argument, or "" when there is none.

    Split on commas at the top level only: a URL is often built by
    concatenation and can carry commas inside its own calls.
    """
    parts, depth, cur = [], 0, ""
    for ch in args:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts[2].strip() if len(parts) > 2 else ""


def test_the_scan_actually_finds_the_calls():
    calls = _calls()
    assert len(calls) >= AT_LEAST, (
        "found only %d window.open calls, expected at least %d: the regex "
        "or the file list has rotted, and an empty scan passes every other "
        "test in this file" % (len(calls), AT_LEAST))


def test_no_shipped_page_asks_for_a_popup():
    """A size in the features is what makes it a popup instead of a tab."""
    popups = [(f, n, _features(a)) for f, n, a in _calls()
              if re.search(r"width\s*=|height\s*=", _features(a))]
    assert popups == [], (
        "these open a popup window instead of a tab:\n"
        + "\n".join("  %s:%d  %s" % p for p in popups))


@pytest.mark.parametrize("name", [p.name for p in SHIPPED])
def test_a_call_that_keeps_its_handle_never_passes_noopener(name):
    """noopener returns null, so polling win.closed never fires again."""
    path = next(p for p in SHIPPED if p.name == name)
    text = path.read_text(encoding="utf-8", errors="replace")
    bad = []
    for m in CALL.finditer(text):
        before = text[:m.start()]
        kept = re.search(r"(var|let|const)\s+\w+\s*=\s*$", before) is not None
        if kept and "noopener" in _features(m.group(1)):
            bad.append((name, before.count("\n") + 1))
    assert bad == [], (
        "these keep the window handle AND pass noopener, so the handle is "
        "always null and completion is never noticed: %s" % (bad,))
