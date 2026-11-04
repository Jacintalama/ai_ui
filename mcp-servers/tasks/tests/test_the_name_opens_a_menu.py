"""The app's name offers its history, a copy, and where it came from.

The last of the four things Ralph's screenshots of ChatGPT's canvas
showed, 2026-11-04: the name in the title bar opens a menu.

Almost none of it is new. Version history is already
"git log -- apps/<slug>/" behind /api/aiuibuilder/<slug>/versions, and
the download is the export the App Builder card has had for months. This
puts them where somebody is actually looking at the app.
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
    start = src.index("function " + name)
    ends = [src.find(m, start + 10)
            for m in ("\n  function ", "\n  // ===== End")]
    return src[start:min(e for e in ends if e != -1)]


# --- it reuses what exists ------------------------------------------------

def test_history_is_the_route_that_already_reads_the_git_log():
    body = _fn("aiuiAppMenu")
    assert "/api/aiuibuilder/" in body
    assert "/versions" in body


def test_download_is_the_export_that_already_exists():
    """Owner-only on the server, because it hands over the full source,
    the git history and the Supabase config that otherwise never lives in
    the app's files."""
    assert "/api/projects/" in _fn("aiuiAppMenu")
    assert "/export" in _fn("aiuiAppMenu")


def test_the_download_is_a_plain_navigation():
    """Fetching it would hold a zip of somebody's app in this page's
    memory for no reason."""
    body = _fn("aiuiAppMenu")
    grab = body[body.index("Download it"):]
    grab = grab[:grab.index("});")]
    assert "window.open(" in grab
    assert "fetch(" not in grab


# --- rolling back is not a hover ------------------------------------------

def test_going_back_asks_first():
    """It throws away everything since, and a menu row is one stray click
    away from a hover."""
    body = _fn("aiuiAppMenu")
    assert "window.confirm(" in body
    back = body.index("window.confirm(")
    post = body.index("/rollback", back)
    assert back < post, "the rollback fires before anything is asked"


def test_the_version_it_is_on_cannot_be_rolled_to():
    """Rolling back to where you already are does nothing and looks like
    a broken button."""
    body = _fn("aiuiAppMenu")
    assert "v.is_current ? null :" in body


def test_the_list_is_cut_short():
    """An app with two hundred commits would otherwise be a menu taller
    than the window."""
    src = _js()
    # That it is USED, not merely declared. Deleting the slice leaves the
    # constant sitting there and the weaker check passes while a
    # two-hundred-commit app fills the window.
    assert "rows.slice(0, AIUI_VERSIONS_SHOWN)" in _fn("aiuiAppMenu")
    n = re.search(r"AIUI_VERSIONS_SHOWN = (\d+)", src)
    assert n and int(n.group(1)) <= 20


# --- getting rid of it -----------------------------------------------------

def test_three_ways_to_dismiss_it():
    """Escape, clicking away, and the name again."""
    body = _fn("aiuiAppMenu")
    assert "e.key === 'Escape'" in body
    assert "!menu.contains(e.target)" in body
    assert "getAttribute('data-for') === slug" in body


def test_its_listeners_are_unhooked_when_it_closes():
    """Left bound, every later Escape and every later click anywhere runs
    this menu's handlers."""
    body = _fn("aiuiAppMenu")
    assert "removeEventListener('keydown', onKey, true)" in body
    assert "removeEventListener('mousedown', onAway, true)" in body


def test_only_one_menu_exists_at_a_time():
    """Opening a second leaves the first floating with nothing to close
    it, because its anchor is gone."""
    assert "getElementById('aiui-app-menu')" in _fn("aiuiAppMenu")


# --- the way in ------------------------------------------------------------

def test_the_name_is_the_way_in():
    body = _fn("aiuiShowAppInline")
    assert "aiuiAppMenu(slug, name)" in body


def test_the_name_says_it_can_be_clicked():
    """It looks like a label. Without a title and a cursor nobody will
    ever press it."""
    body = _fn("aiuiShowAppInline")
    assert "name.title = 'History, download, and where it came from'" in body
    assert "cursor:pointer" in body


def test_history_failing_says_so():
    """An empty menu where history should be reads as "this app has no
    history", which is a different and alarming thing."""
    assert "History is not available" in _fn("aiuiAppMenu")
