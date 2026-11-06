"""The Pending Tasks panel is gone, and the App Builder entry is not.

Removed 2026-11-06 on request. It tracked action items pulled out of
meeting transcripts (RESEARCH, ASK_USER, INTEGRATE, OUTREACH): 11 rows in
the whole database, newest 13 May, several of them dead test rows.

The reason this has a test rather than just a deletion is that the panel
shared one 1992-line file with the sidebar entries for App Builder, Video
Generation and Cron Jobs, and shared its table with 288 BUILD rows, which
is every app ever built here. Deleting the file would have taken the App
Builder's own entry point with it. So the file was cut, not dropped, and
this pins both halves of that: the panel stays gone, and the half that
had nothing to do with it keeps working.
"""
import os
import re

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "static", "task-panel.js")


def _src():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


# --- the panel is gone ---------------------------------------------------

@pytest.mark.parametrize("gone", [
    "aiui-tp-",               # every class the panel's markup used
    "aiui-tp-title",          # its header class
    "window.aiuiTaskPanel",   # the handle other code opened it by
    "injectIntegrationsMenuEntry",   # the "Tasks" entry in the + menu
    "function syncFab",       # the floating launcher
    "function refreshAll",    # its polling
])
def test_no_trace_of_the_panel_is_left(gone):
    assert gone not in _src(), (
        "the task panel is supposed to be gone, but %r is still here" % gone)


def test_nothing_still_calls_what_was_removed():
    """A dangling call is a ReferenceError at load, which would take the
    sidebar entries down with it: everything in this file is one IIFE."""
    src = _src()
    for name in ("syncFab(", "refreshAll(", "setOpen(", "_fabPaneOpen",
                 "_initDone"):
        assert name not in src, "dangling reference to " + name


def test_the_file_still_parses_as_one_piece():
    """Cheap proof there is no half-removed block. Counting braces is not
    a parser, but an unbalanced cut shows up here immediately."""
    src = _src()
    assert src.count("{") == src.count("}"), "braces do not balance"
    assert src.count("(") == src.count(")"), "parentheses do not balance"


# --- the half that must survive -----------------------------------------

@pytest.mark.parametrize("kept", [
    "App Builder",
    "Video Generation",
    "Cron Jobs",
    "injectSidebarBuildWebsiteEntry",
    "data-aiui-build-website",
    "function openAiuiEmbed",
    "function closeAiuiEmbed",
    "watchSpaNavigation",
])
def test_the_sidebar_and_panes_are_untouched(kept):
    assert kept in _src(), (
        "%r went with the panel; that is the App Builder's own entry "
        "point, not the task feature" % kept)


def test_the_auth_gate_stayed_because_the_sidebar_uses_it():
    """App Builder is admin-only and onAuthRoute keeps every injection off
    the sign-in page. Both live in the section the panel also used."""
    src = _src()
    assert "async function isAdmin()" in src
    assert "function onAuthRoute()" in src
    assert src.count("isAdmin()") >= 3, (
        "the sidebar entries no longer check who is asking")


def test_the_three_entries_are_still_injected_at_load():
    assert re.search(r"^\s*injectSidebarBuildWebsiteEntry\(\);",
                     _src(), re.M), "nothing injects the sidebar entries"


# --- what was deliberately NOT removed ----------------------------------

def test_the_build_pipeline_was_not_touched():
    """288 BUILD rows share the table the 11 action items were in. The
    App Builder creates, reads and finishes tasks through these, and none
    of it is part of what was removed.
    """
    here = os.path.dirname(__file__)
    for module in ("routes_aiuibuilder.py", "routes_execution.py",
                   "light_runner.py", "build_progress.py"):
        assert os.path.isfile(os.path.join(here, "..", module)), module
