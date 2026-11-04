"""A finished build shows the app, running, in the conversation.

A build used to end with a URL, so seeing what had just been made meant
opening a second tab and coming back.

The shape is the one Ralph's boss asked for on 2026-11-04, pointing at
ChatGPT's canvas: a compact panel in the thread with a title bar, the
LIVE site inside it, and a way to make it bigger. Not a screenshot, and
not a link.

Structural, because this file is vanilla JS served as a static asset with
no harness, the same compromise as test_connect_button.py. What these pin
down is the handful of decisions that would be quietly wrong.
"""
import os
import re

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _inline():
    """The function itself, not the whole file."""
    src = _js()
    start = src.index("function aiuiShowAppInline")
    return src[start:src.index("\n  function ", start + 10)]


# --- the decision that would be quietly wrong ------------------------------

def test_the_app_is_served_by_its_own_published_url():
    """main.py::serve_published_app injects the project's Supabase url and
    anon key AT REQUEST TIME, so they are in no file of the app. Anything
    that assembles the page another way shows an app whose database
    quietly does not work, while the same app in a tab works."""
    body = _inline()
    assert "/tasks/preview-app/" in body
    for forbidden in ("srcdoc", "innerHTML = ", "document.write"):
        assert forbidden not in body, (
            "the app is being assembled rather than fetched: " + forbidden)


def test_it_is_the_running_app_not_a_picture_of_one():
    """A screenshot was the first attempt and was sent back: the point is
    to use the thing, scroll it and click it, in the conversation."""
    body = _inline()
    assert "createElement('iframe')" in body
    assert "frame.src = url" in body
    assert "thumb.jpg" not in body


def test_the_slug_is_checked_before_it_becomes_a_url():
    """It arrives from a task row. Building a URL from one without looking
    is how the schedules tool grew a directory traversal."""
    assert re.search(r"test\(String\(slug", _inline())


def test_the_frame_cannot_navigate_the_chat():
    """Our own app on our own origin, so not a trust boundary. The sandbox
    is here so a built page cannot take the chat out from under the person
    reading it."""
    body = _inline()
    sandbox = re.search(r"setAttribute\('sandbox', '([^']*)'\)", body)
    assert sandbox, "the frame has no sandbox"
    assert "allow-top-navigation" not in sandbox.group(1)


def test_the_app_keeps_its_own_origin():
    """It is served from our origin and reads the session. An opaque
    origin would leave the panel unable to load anything."""
    body = _inline()
    sandbox = re.search(r"setAttribute\('sandbox', '([^']*)'\)", body)
    assert sandbox and "allow-same-origin" in sandbox.group(1)


def test_it_is_drawn_once_per_app():
    """The watcher polls every few seconds. Without this the chat fills
    with copies of the same app."""
    assert "getElementById(id)" in _inline()


def test_it_loads_lazily():
    """A finished build sits in the history. Every one of them loading on
    every page open would be a tab full of running apps."""
    body = _inline()
    assert "'loading', 'lazy'" in body


# --- small in the chat, bigger on request ---------------------------------

def test_it_is_small_by_default():
    """It is one turn in a conversation, not the page. The boss's words
    were "small in the chat like minimize"."""
    src = _js()
    small = re.search(r"AIUI_APP_H = '(\d+)rem'", src)
    assert small, "the panel has no default height"
    assert int(small.group(1)) <= 28, "that is not small in a chat"


def test_it_can_be_made_bigger():
    """A landing page in 22rem is a peek. Somebody who wants to look
    properly should not have to leave the conversation to do it."""
    src = _js()
    assert "AIUI_APP_H_BIG" in src
    body = _inline()
    assert "grow.addEventListener('click'" in body


def test_making_it_bigger_is_reversible():
    """A one-way expand leaves a chat with an 80vh frame wedged in it."""
    body = _inline()
    assert "big = !big" in body
    assert "big ? AIUI_APP_H_BIG : AIUI_APP_H" in body


def test_the_controls_say_what_they_do():
    """Two glyphs in a corner. Without a label they are a guess, and a
    screen reader has nothing at all."""
    body = _inline()
    # Inside the BUTTON MAKER, not a count over the function. Deleting the
    # label there still leaves two other setAttribute lines, so the count
    # passed while every button built by it lost its name.
    maker = body[body.index("function iconBtn("):]
    maker = maker[:maker.index("return el;")]
    assert "setAttribute('aria-label', label)" in maker
    assert "el.title = label" in maker
    assert "Make it bigger" in body


def test_there_is_still_a_way_out_to_a_tab():
    """A panel is a window on a thing. Anybody who wants the app properly
    should not have to hunt for the URL."""
    body = _inline()
    # The title AND the label. "Open in a new tab" appears on both lines,
    # so checking the string once passed with the visible tooltip blanked.
    assert "out.title = 'Open in a new tab'" in body
    assert "out.setAttribute('aria-label', 'Open in a new tab')" in body
    assert "noopener" in body
    assert "_blank" in body


# --- when it is drawn ------------------------------------------------------

def test_only_a_completed_build_shows_an_app():
    """A failed build has nothing to show, and one waiting on an answer
    has something to answer rather than something to look at."""
    src = _js()
    assert re.search(r"if \(String\(task\.status \|\| ''\) === 'completed'"
                     r" && task\.built_app_slug\) \{", src)


def test_it_is_drawn_before_the_close_rather_than_after():
    """Closing can take another tick or be done by another tab. The person
    is looking at the chat now."""
    src = _js()
    drawn = src.index("aiuiShowAppInline(chatId, task.built_app_slug)")
    closed = src.index("return aiuiCloseBuild(chatId, id, text);", drawn - 400)
    assert drawn < closed
