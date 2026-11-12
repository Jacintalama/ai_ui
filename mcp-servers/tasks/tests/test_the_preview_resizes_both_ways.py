"""A preview could be dragged taller, never wider.

Ralph, 2026-11-12: "also the size cant be widen only hight i can adjust..
please add that also".

The grab bar under a preview has moved height since 2026-11-11, and height
alone is half an answer: a landing page is wide. The chat column it sits in
is roughly 720 pixels on a 1920 screen, so the page is rendered into a
third of the window and read at a third of the size, while two thirds of
the screen sit empty on either side.

HOW WIDTH IS DONE HERE, and why not simply `width`:

    The box lives in the message column's normal flow. Setting a width
    larger than that column makes it overflow to one side and leaves it
    off-centre. Symmetric NEGATIVE MARGINS keep it in flow, centred, and
    growing both ways, which is what "wider" looks like to the person
    dragging it.

So what is stored is not a width, it is the EXTRA beyond the column, which
also survives the column itself changing width (a narrower window, the side
panel opening) without being meaningless.
"""
import os
import re

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    """One top-level function's source."""
    src = _js()
    start = src.index("\n  function " + name + "(")
    rest = src[start + 3:]
    end = rest.index("\n  function ")
    return rest[:end]


# --- the drag moves both ways ---------------------------------------------

def test_the_handle_is_dragged_sideways_as_well_as_up_and_down():
    body = _fn("aiuiSizeHandle")
    assert "clientY" in body, "the height drag is gone"
    assert "clientX" in body, (
        "the handle still reads only vertical movement, so it can only be "
        "made taller")


def test_the_handle_says_it_moves_in_both_directions():
    """A bar that resizes two ways and shows a one-way cursor is a control
    that hides half of itself."""
    body = _fn("aiuiSizeHandle")
    assert "cursor:ns-resize" not in body.replace(" ", ""), (
        "the cursor still claims up and down only")


def test_the_label_says_what_the_arrows_do():
    """The only way to resize this for somebody who does not drag."""
    body = _fn("aiuiSizeHandle")
    label = body[body.index("aria-label"):]
    label = label[:label.index(");")].lower()
    assert "width" in label or "wider" in label


def test_the_arrows_move_width_and_height_separately():
    body = _fn("aiuiSizeHandle")
    assert "ArrowLeft" in body and "ArrowRight" in body
    assert "ArrowUp" in body and "ArrowDown" in body
    # Left and right used to be a second way to change HEIGHT, which left
    # no key for width at all. Asserted on which function each arrow
    # reaches rather than on any word near it: the branch is one line and
    # the only thing that matters about it is where it goes.
    def _branch(key):
        at = body.index("'" + key + "'")
        return body[at:body.index("\n", at)]

    for key in ("ArrowLeft", "ArrowRight"):
        assert "widen(" in _branch(key), key + " does not change the width"
        assert "apply(" not in _branch(key), key + " still changes the height"
    for key in ("ArrowUp", "ArrowDown"):
        assert "apply(" in _branch(key), key + " no longer changes the height"
        assert "widen(" not in _branch(key)


# --- it cannot be dragged into uselessness --------------------------------

def test_a_preview_can_never_be_dragged_wider_than_the_window():
    body = _fn("aiuiMaxAppExtra")
    assert "innerWidth" in body, (
        "nothing stops a drag running past the edge of the screen")


def test_the_widest_is_measured_against_the_column_it_sits_in():
    """The column, not the box: the box's own width already contains
    whatever extra is applied, so measuring it would compound every drag."""
    body = _fn("aiuiMaxAppExtra")
    assert "parentElement" in body


def test_a_preview_can_never_be_dragged_narrower_than_its_column():
    """Zero extra is the floor. Negative extra would be positive margins,
    which is a preview shrinking away from a column that fits it."""
    body = _fn("aiuiClampAppExtra")
    assert "Math.max(0" in body.replace(" ", "") or "Math.max( 0" in body


# --- remembered, like the height ------------------------------------------

def test_the_width_is_remembered():
    assert "aiui-app-width" in _js()


def test_the_width_is_remembered_per_browser_not_per_app():
    """Same argument the height already makes: this is an answer about a
    screen and a pair of eyes, not about one landing page."""
    src = _js()
    key = src[src.index("AIUI_APP_W_KEY"):]
    key = key[:key.index("\n")]
    assert "slug" not in key


def test_a_stored_width_can_never_reach_the_page_unclamped():
    """localStorage is editable and shared with everything else on this
    origin, and it survives a release that changes what a value means. It
    also survives the window being made smaller, which is the ordinary way
    a once-legal value stops fitting.

    Asserted where the value REACHES THE PAGE rather than where it is
    read: that is one function, and it covers the stored value, the drag
    and the arrows with a single rule. Clamping at the read would leave
    the other two paths to be remembered separately.
    """
    body = _fn("aiuiApplyAppWidth")
    assert "aiuiClampAppExtra" in body


def test_a_browser_with_storage_switched_off_still_resizes():
    """It just does not remember. A thrown error halfway through a drag is
    worse than forgetting."""
    body = _fn("aiuiSaveAppExtra")
    assert "try {" in body and "catch" in body


# --- the side panel owns its own size -------------------------------------

def test_the_extra_width_is_dropped_when_it_moves_beside_the_chat():
    """Beside the chat the PANE sets the size, and the box left behind in
    the thread is empty. Extra margins on it would push an empty box out
    over the conversation."""
    body = _fn("aiuiSplitOpen")
    assert "aiuiApplyAppWidth(box, 0)" in body


def test_the_extra_width_comes_back_when_it_returns_to_the_chat():
    body = _fn("aiuiSplitClose")
    assert "aiuiApplyAppWidth" in body
    assert "aiuiSavedAppExtra()" in body


# --- and it is applied at all ---------------------------------------------

def test_a_preview_opens_at_the_width_it_was_left_at():
    """Remembering a size and not restoring it is worse than not
    remembering: the control looks broken every time the page reloads."""
    body = _fn("aiuiShowAppInline")
    assert "aiuiApplyAppWidth" in body
    assert "aiuiSavedAppExtra()" in body


def test_the_handle_is_given_the_box_it_has_to_widen():
    """It only ever received the frame, which is why width was never
    possible: the frame is 100% of a box nobody handed it."""
    body = _fn("aiuiShowAppInline")
    assert "aiuiSizeHandle(frame, box)" in body


def test_width_is_applied_as_symmetric_negative_margins():
    body = _fn("aiuiApplyAppWidth")
    assert "marginLeft" in body and "marginRight" in body
    assert "-" in body, "positive margins would make it narrower, not wider"
