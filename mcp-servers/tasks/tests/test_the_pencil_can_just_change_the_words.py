"""Two ways out of the same pencil: change the words, or ask for a change.

Ralph, 2026-11-12: "user can be able to eid that in here... by selecting or
user can manualy change the words... or ask agent to do it... you know..
uiser can see easily and fast since its only edit... its not that soo long".

Pointing at something and asking for a change runs an agent, which is a
build: minutes, a commit, a reload. That is the right price for "make the
hero more dramatic" and the wrong one for a typo in a rating.

So the panel offers both, and the fast one is first, because it is the one
that is right most often:

    Changing: 4.9/5 from 2,300+ happy sippers
    [ 4.9/5 from 2,300+ happy sippers        ] [ Replace ]
    or ask for a change
    [ What would you like to change?         ]

The words box is PRE-FILLED with what is on the page, because the job is
almost always to edit them rather than to retype them, and because seeing
them in the box is what makes it obvious the box is for the words
themselves and the one below it is for an instruction.
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
    src = _js()
    start = src.index("\n  function " + name + "(")
    rest = src[start + 3:]
    return rest[:rest.index("\n  function ")]


# --- what was pointed at ---------------------------------------------------

def test_the_whole_text_is_carried_not_only_the_part_the_agent_is_shown():
    """The agent's prompt gets 200 characters, which is plenty to describe
    an element. A SWAP has to match the file exactly, so a truncated
    string would replace a prefix and leave the tail behind, which is a
    mangled page rather than a failed change."""
    body = _fn("aiuiAnnotateOn")
    assert "full:" in body
    full = body[body.index("full:"):]
    full = full[:full.index("\n")]
    assert "slice(" not in full, "the words used for the swap are truncated"


def test_the_description_the_agent_gets_is_still_capped():
    body = _fn("aiuiAnnotateOn")
    text = body[body.index("text:"):]
    text = text[:text.index("\n")]
    assert "slice(0, 200)" in text or "slice(0,200)" in text


# --- the fast way ----------------------------------------------------------

def _inline():
    return _fn("aiuiShowAppInline")


def test_there_is_a_box_holding_the_words_themselves():
    body = _inline()
    assert "var words = document.createElement('input')" in body


def test_the_words_box_is_prefilled_with_what_is_on_the_page():
    body = _inline()
    assert "words.value = pick.full" in body


def test_changing_the_words_does_not_go_to_the_agent():
    """The whole point. A text swap is a route of its own, which writes
    the file and commits, with no build anywhere in it."""
    body = _inline()
    assert "/text'" in body
    swap = body[body.index("/text'"):][:400]
    assert "enhance" not in swap


def test_the_swap_sends_what_was_there_and_what_to_put_there():
    body = _inline()
    swap = body[body.index("/text'"):][:500]
    assert "old:" in swap and "new:" in swap


def test_the_swap_sends_the_full_words_not_the_shown_ones():
    body = _inline()
    swap = body[body.index("/text'"):][:500]
    assert "picked.full" in swap, (
        "sending the truncated description would replace a prefix")


def test_the_page_is_reloaded_so_the_change_can_be_seen():
    """The file changed under a frame that has every reason to believe it
    did not, which is the same reason the build watcher cache-busts."""
    body = _inline()
    after = body[body.index("/text'"):][:1400]
    assert "frame.src" in after
    assert "?changed=" in after


def test_a_swap_that_cannot_be_sent_hands_the_boxes_back():
    """The same shape of bug as the enhance box had this morning: a throw
    while the request is still being built leaves no promise to catch."""
    body = _inline()
    send = body[body.index("function doSwap"):]
    send = send[:send.index("\n    }") + 6]
    assert "try {" in send and "catch" in send
    tail = send[send.index("} catch"):]
    assert "words.disabled = false" in tail


def test_the_boxes_come_back_when_the_pencil_is_put_down():
    body = _inline()
    stop = body[body.index("function annotateStop"):]
    stop = stop[:stop.index("\n    }") + 6]
    assert "words.disabled = false" in stop
    assert "asked.disabled = false" in stop


def test_the_same_words_are_not_sent_as_a_change():
    """A round trip, a commit and a reload to change nothing at all."""
    body = _inline()
    assert "=== picked.full" in body or "!== picked.full" in body


# --- the slow way is still there ------------------------------------------

def test_asking_the_agent_is_still_offered():
    body = _inline()
    assert "/enhance'" in body
    assert "aiuiAnnotatePrompt(picked, said)" in body


def test_the_two_boxes_are_told_apart_in_words():
    """Two inputs with no label between them is a guessing game."""
    body = _inline()
    assert "or ask for a change" in body


def test_an_element_with_no_words_is_only_offered_the_agent():
    """An image, a spacer, a wrapper around other elements. There is
    nothing to put in a words box, and showing an empty one invites a
    change that can only be refused.

    Asserted on the row being HIDDEN rather than on the shape of the
    test that hides it: what matters is that both halves of the offer
    disappear together, so the panel never shows a words box over an
    element that has none.
    """
    body = _inline()
    pick = body[body.index("askWhat.textContent = 'Changing: '"):][:900]
    assert "pick.full" in pick, "nothing looks at whether there are words"
    assert "wordsRow.style.display" in pick
    assert "orLine.style.display" in pick, (
        "the label survives its box, so the panel reads 'or ask for a "
        "change' with nothing above it")
