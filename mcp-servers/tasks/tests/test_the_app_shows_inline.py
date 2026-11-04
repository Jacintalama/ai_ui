"""A finished build shows the app, not a link to it.

A build used to end with a URL, so seeing what had just been made meant
opening a second tab and coming back. The app now appears under the reply.

Structural, because this file is vanilla JS served as a static asset with
no harness, the same compromise as test_connect_button.py. What these pin
down is the one decision that is not obvious and would be quietly wrong.
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

def test_the_app_opens_at_its_own_published_url():
    """main.py::serve_published_app injects the project's Supabase url and
    anon key AT REQUEST TIME, so they are not in the app's files at all.
    Anything that assembles the page another way serves an app whose
    database silently does not work, while the same app in a tab works."""
    body = _inline()
    assert "/tasks/preview-app/" in body
    for forbidden in ("srcdoc", "innerHTML = ", "document.write"):
        assert forbidden not in body, (
            "the app is being assembled rather than fetched: " + forbidden)


def test_it_is_a_card_with_a_picture_of_the_app():
    """Ralph, 2026-11-04, pointing at the App Builder page: "i want it
    something like this ... in the chat it self". A card with the
    screenshot, the name and a way in, not a link and not a bare frame."""
    body = _inline()
    assert "/thumb.jpg" in body
    # That it REACHES the card, not merely that one was created. An img
    # built and never appended passes the weaker check while the card
    # shows a grey box forever.
    assert "shot.appendChild(img)" in body
    assert "img.src = " in body
    assert "Open preview" in body


def test_the_picture_is_waited_for_rather_than_given_up_on():
    """routes_projects answers 404 the first time and QUEUES the capture,
    so an app built seconds ago has no picture yet. Giving up on the
    first error means the card never shows one."""
    body = _inline()
    assert "img.onerror" in body
    assert "AIUI_SHOT_TRIES" in body


def test_each_retry_asks_for_a_new_url():
    """A browser caches a 404 as readily as a picture. Without this it
    would re-read the cached miss and never see the shot that arrived."""
    body = _inline()
    assert "thumb.jpg?t=" in body


def test_giving_up_says_so():
    """An empty grey box reads as something broken."""
    assert "No picture yet" in _inline()


def test_the_slug_is_checked_before_it_becomes_a_url():
    """It arrives from a task row. A slug is already constrained there, and
    building a URL from one without looking is how the schedules tool grew
    a directory traversal."""
    assert re.search(r"test\(String\(slug", _inline())


def test_it_is_drawn_once_per_app():
    """The watcher polls every few seconds. Without this the chat fills
    with copies of the same app."""
    assert "getElementById(id)" in _inline()


# --- when it is drawn ------------------------------------------------------

def test_only_a_completed_build_shows_an_app():
    """A failed build has nothing to show, and one waiting on an answer
    has something to answer rather than something to look at."""
    src = _js()
    hook = re.search(r"if \(String\(task\.status \|\| ''\) === 'completed'"
                     r" && task\.built_app_slug\) \{", src)
    assert hook, "the preview is not gated on the build having completed"


def test_it_is_drawn_before_the_close_rather_than_after():
    """Closing can take another tick or be done by another tab. The person
    is looking at the chat now."""
    src = _js()
    drawn = src.index("aiuiShowAppInline(chatId, task.built_app_slug)")
    closed = src.index("return aiuiCloseBuild(chatId, id, text);", drawn - 400)
    assert drawn < closed


def test_there_is_still_a_way_into_the_app():
    """A card is a picture of a thing, not the thing. The way in is the
    button, which is what the App Builder card calls it too."""
    assert "Open preview" in _inline()


def test_the_link_is_safe_to_click():
    body = _inline()
    assert "noopener" in body
    assert "_blank" in body
