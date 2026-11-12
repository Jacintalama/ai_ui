"""The pencil stayed in the chat when the app moved beside it.

Ralph, 2026-11-12, looking at an app open in the side panel: "also when we
are in here add the pencil also so user can be able to eid that in here".

Moving the app out of the thread hid the whole bar it came with, so the two
controls that are most useful on a big preview, pointing at a part of the
page and changing its colours, were only available on the small one. The
side panel had a name, an open-in-a-tab link and a close button.

Everything needed is already built. The split MOVES the iframe rather than
rebuilding it, which is why pointing still works once it is over there:
`aiuiAnnotateOn` reaches into `frame.contentDocument`, and it is the same
element. So the fix is to move the controls the same way, and to put them
back when the app comes home.
"""
import os

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    src = _js()
    start = src.index("\n  function " + name + "(")
    rest = src[start + 3:]
    return rest[:rest.index("\n  function ")]


# --- the controls travel ---------------------------------------------------

def test_the_panel_takes_the_controls_it_is_given():
    body = _fn("aiuiSplitOpen")
    assert "tools" in body, "the panel still cannot be given any controls"
    assert "footers" in body, (
        "the ask box and the appearance panel sit UNDER the app, so they "
        "are not head controls")


def test_the_pencil_and_the_palette_are_handed_over():
    """The two that are worth more on a big preview than a small one."""
    body = _fn("aiuiShowAppInline")
    call = body[body.index("aiuiSplitOpen("):]
    call = call[:call.index(")")]
    assert "note" in call, "the pencil is left behind"
    assert "paint" in call, "the appearance button is left behind"


def test_the_ask_box_travels_with_the_pencil():
    """A pencil that opens its question back in the hidden thread is worse
    than no pencil: it looks like the button did nothing."""
    body = _fn("aiuiShowAppInline")
    call = body[body.index("aiuiSplitOpen("):]
    call = call[:call.index(")")]
    assert "ask" in call


def test_the_appearance_panel_travels_with_its_button():
    body = _fn("aiuiShowAppInline")
    call = body[body.index("aiuiSplitOpen("):]
    call = call[:call.index(")")]
    assert "look.el" in call


# --- and they come back ----------------------------------------------------

def test_every_control_that_moved_is_put_back():
    body = _fn("aiuiSplitClose")
    assert "moved" in body, (
        "nothing puts the borrowed controls back, so closing the panel "
        "destroys the pencil")


def test_a_control_goes_back_where_it_was_not_merely_into_the_bar():
    """Appending restores the control and reorders the bar: the pencil
    comes back sitting after the open-in-a-tab link. Order is the only
    thing a row of icons has."""
    body = _fn("aiuiSplitOpen")
    assert "nextSibling" in body


def test_they_are_put_back_before_the_panel_is_destroyed():
    """Order matters: removing the panel first takes everything inside it
    out of the document with it."""
    body = _fn("aiuiSplitClose")
    assert body.index("moved") < body.index("removeChild(s.panel)")


# --- nothing that already worked is now required ---------------------------

def test_a_panel_given_no_controls_still_opens():
    """The arguments are optional. A future caller with no bar of its own
    must not get a crash instead of a panel."""
    body = _fn("aiuiSplitOpen")
    assert "tools || []" in body or "(tools" in body
    assert "footers || []" in body or "(footers" in body


def test_the_app_is_still_moved_and_never_rebuilt():
    """The reason pointing works at all on the far side: same element,
    same contentDocument. Rebuilding the iframe would reload the app and
    throw away the scroll position with it."""
    body = _fn("aiuiSplitOpen")
    assert "holder.appendChild(frame)" in body
    assert "createElement('iframe')" not in body
