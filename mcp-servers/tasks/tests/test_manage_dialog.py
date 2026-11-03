"""The Connections dialog: the one that says Manage Trello.

Structural, because this file is vanilla JS with no test harness, the same
compromise as test_connect_button.py. These pin the two things reported
from a screenshot on 2026-11-03, both of which were invisible to every
test that existed and obvious the moment somebody looked at the box.

**The buttons broke their own words.** Four of them at their natural widths
come to more than the box is wide, and flex shrinks before it wraps, so
they were sized below their own text: "Disconnec t", "Cance l", "Connec t".
Nothing was broken underneath, which is the point. A dialog that reads like
that is one nobody trusts enough to press.

**One click was hidden from anyone who had used it.** The offer was gated
on `meta.oauth && !connected`, so somebody who connected Trello in one tap
and then wanted a different account was shown the four step paste form and
nothing else. The path they had just used was the one path the page would
not offer them again.
"""
import os
import re
import shutil
import subprocess

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _manage_dialog(js=None):
    """Just this dialog's construction, not the whole file.

    This file builds several dialogs and several button rows, so a bare
    search finds whichever comes first and quietly measures the wrong one.
    The boundary is structural: from the line that titles this dialog to
    the point it is put on the page.
    """
    js = js if js is not None else _js()
    start = js.index("(connected ? 'Manage ' : 'Connect ')")
    end = js.index("wrap.appendChild(box);", start)
    return js[start:end]


# --- it still parses ----------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="no node here")
def test_the_file_parses():
    """A syntax error in this file takes the whole Connections panel with
    it, and nothing else in the suite would notice: it is served as a
    static asset, never imported."""
    out = subprocess.run([shutil.which("node"), "--check", os.path.abspath(JS)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# --- the buttons keep their words together ------------------------------------

def test_the_button_row_wraps_rather_than_squashing():
    """flex shrinks before it wraps, which is what sized the buttons below
    their own text."""
    row = re.search(r"row\.style\.cssText\s*=\s*'display:flex;([^\n]*)",
                    _manage_dialog())
    assert row, "the dialog's button row moved; re-point this test"
    assert "flex-wrap:wrap" in row.group(0)


def test_every_dialog_button_keeps_its_text_on_one_line():
    """The four that were reported. Checked by name, so adding a fifth
    without this is the failure rather than the silence."""
    js = _manage_dialog()
    # The definition, not the words anywhere in the file. Every button
    # referencing an empty KEEP_WHOLE would read as a pass while squashing
    # exactly as before.
    keep = re.search(r"var KEEP_WHOLE = '([^']*)';", js)
    assert keep, "KEEP_WHOLE is gone; the buttons have nothing holding them"
    assert "white-space:nowrap" in keep.group(1)
    for button in ("test.style.cssText", "dis.style.cssText",
                   "cancel.style.cssText", "go.style.cssText"):
        line = re.search(re.escape(button) + r"\s*=\s*(.*?);\n", js, re.S)
        assert line, button
        assert "KEEP_WHOLE" in line.group(1), (
            button + " can be squashed below its own text again")


# --- one click is offered to somebody who already connected -------------------

def test_the_one_click_offer_is_not_gated_on_being_disconnected():
    """The bug itself, written as the thing that must not come back."""
    js = _js()
    # The code form, not the bare words: the comment above it quotes the
    # old condition on purpose, and a test that cannot tell a comment from
    # code would forbid writing down what was fixed.
    assert "if (meta.oauth && !connected)" not in js, (
        "one click is hidden from anyone who already connected, which is "
        "everyone who would want to swap accounts")
    assert re.search(r"if \(meta\.oauth\) \{", js)


def test_the_button_says_reconnect_when_there_is_something_to_replace():
    """"Connect with Trello" on a dialog headed Manage Trello reads as a
    second connection rather than a replacement."""
    js = _js()
    assert "'Reconnect with '" in js
    assert "'Connect with '" in js


def test_a_failed_reconnect_is_not_read_as_a_success():
    """The trap this opened. When they were already connected the card
    still says Connected whatever happens in the popup, so closing the
    dialog on that would report success for something that did not happen
    and quietly leave the old credential in place.

    The callback page posts `ok`, and both of them do: the OAuth2 one and
    Trello's fragment page. That is the only account of what happened.
    """
    js = _js()
    assert "sawOk" in js, "nothing reads what the callback page said"
    assert re.search(r"replacing \? \(sawOk === true\) : connState\[app\.id\]", js)


def test_a_popup_closed_early_says_nothing_changed():
    """Three outcomes, and somebody can act on each only if they are told
    apart: it worked, it was refused, the window went away."""
    js = _js()
    assert "sawOk === false" in js
    assert "Nothing" in js and "still in place" in js


def test_the_paste_form_is_still_there_underneath():
    """One click is an addition, not a replacement. A deployment with no
    app registered, and anyone who would rather paste, both keep what they
    had."""
    js = _js()
    assert "or paste a token" in js
    assert "or paste a different credential" in js
