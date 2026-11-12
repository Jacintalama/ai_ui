"""Beside the chat, nothing said a change was happening.

Ralph, 2026-11-12, with the app open in the side panel: "it could work the
manual but i tried the agent and it work... just add a skeleton animation
loading kinda so user knows its working".

The progress WAS being reported. `aiuiWatchChange` writes "Making that
change..." with `aiuiBuildLine`, and that line goes in the CHAT. The side
panel covers half the screen and the chat is behind it, so the one place
the work was announced is the one place that cannot be seen while watching
the app it is changing.

So the panel gets its own. A thin strip across the top of the frame,
shimmering, with whatever the build step is currently saying.

ACROSS THE TOP, not over the whole frame. The existing cover
(`aiuiCoverWhileLoading`) hides everything behind a skeleton, which is
right for an app that has not arrived yet and wrong for one being changed:
an enhance takes minutes, and hiding somebody's page for minutes to tell
them it is busy costs more than it gives. They are watching it to see it
change.
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


# --- it exists and it shimmers --------------------------------------------

def test_there_is_a_strip_that_says_work_is_happening():
    assert "\n  function aiuiWorkingSay(" in _js()
    assert "\n  function aiuiWorkingDone(" in _js()


def test_it_uses_the_shimmer_that_already_exists():
    """Not a second animation. One vocabulary for "this is coming"."""
    body = _fn("aiuiWorkingSay")
    assert "aiui-shimmer" in body
    assert "aiuiMotion()" in body


def test_it_does_not_cover_the_app_it_is_changing():
    """An enhance takes minutes. They are watching it to see it change."""
    body = _fn("aiuiWorkingSay")
    assert "bottom:0" not in body.replace(" ", ""), (
        "the strip covers the whole frame")
    assert "top:0" in body.replace(" ", "")


def test_it_is_found_again_rather_than_stacked():
    """Called on every poll of the watcher: once a second for minutes."""
    body = _fn("aiuiWorkingSay")
    assert "data-aiui-working" in body
    assert "querySelector" in body


def test_it_can_be_attached_wherever_the_frame_currently_is():
    """The frame MOVES between the thread and the side panel, and the
    strip has to appear in whichever one the person is looking at."""
    body = _fn("aiuiWorkingSay")
    assert "parentNode" in body
    assert "position" in body, (
        "the holder must be positioned or an absolute strip escapes it")


def test_a_frame_that_went_away_is_not_an_error():
    body = _fn("aiuiWorkingSay")
    assert "if (!" in body or "return" in body


# --- both kinds of change use it ------------------------------------------

def test_the_agent_change_says_what_the_build_step_is_doing():
    """The watcher already knows: it reads build_step_said every poll and
    has been putting it in the chat, which is behind the panel."""
    body = _fn("aiuiWatchChange")
    assert "aiuiWorkingSay(" in body
    assert "build_step_said" in body


def test_the_agent_change_stops_saying_it_when_it_lands():
    body = _fn("aiuiWatchChange")
    done = body[body.index("status === 'completed'"):][:600]
    assert "aiuiWorkingDone(" in done


def test_a_change_that_failed_also_stops_saying_it():
    """A strip that shimmers forever after a failure is worse than none:
    it says work is happening when none is."""
    body = _fn("aiuiWatchChange")
    failed = body[body.index("status === 'failed'"):][:600]
    assert "aiuiWorkingDone(" in failed


def test_the_watcher_giving_up_stops_saying_it_too():
    """Thirty minutes is the cap, and it is reached by returning rather
    than by either of the two endings above."""
    body = _fn("aiuiWatchChange")
    give_up = body[body.index("AIUI_CHANGE_GIVE_UP_MS"):][:400]
    assert "aiuiWorkingDone(" in give_up


def test_the_word_swap_says_it_too():
    """It is fast, but it still writes a file, commits and reloads."""
    body = _fn("aiuiShowAppInline")
    swap = body[body.index("function doSwap"):][:1600]
    assert "aiuiWorkingSay(" in swap


def test_the_word_swap_stops_saying_it_if_it_is_refused():
    body = _fn("aiuiShowAppInline")
    swap = body[body.index("function doSwap"):][:2200]
    tail = swap[swap.index(".catch("):]
    assert "aiuiWorkingDone(" in tail


# --- and the reason that h1 refused ---------------------------------------
#
# The screenshot that came with the request shows the words box holding
#
#     A cup thatholds the heat,not you back
#
# with no space after "that" or after the comma. That heading is
#
#     <h1>A cup that<br>holds the heat,<br>not you back.</h1>
#
# and `textContent` contributes nothing for a <br>, so the lines run
# together into a string that appears nowhere in the file. The swap
# refused, correctly, and said to ask the agent instead, which he did and
# which worked.
#
# Refusing correctly is still the wrong experience: the box should not
# have been offered. An element with element children of its own cannot be
# matched as one run of text, and that is knowable before anything is
# typed.

def test_the_words_box_is_only_offered_when_the_text_is_one_run():
    body = _fn("aiuiAnnotateOn")
    assert "children.length" in body, (
        "nothing checks whether the element's text is contiguous, so a "
        "heading split by <br> offers a box that can only refuse")


def test_an_element_made_of_other_elements_still_gets_the_agent():
    """The agent reads the description, finds the heading and changes it.
    That path has no such limit and is what it is for."""
    body = _fn("aiuiAnnotateOn")
    assert "text:" in body
    text = body[body.index("text:"):]
    text = text[:text.index("\n")]
    assert "children" not in text, (
        "the agent's description must not be blanked as well")
