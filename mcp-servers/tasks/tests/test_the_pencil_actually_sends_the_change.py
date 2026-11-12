"""The pencil pointed at something, asked what to change, and did nothing.

Ralph, 2026-11-12, with screenshots: "i tried to use the pencil and test the
agent to chat what to change in it... but the thing is it didnt change it...
it didnt do anything.. once i submitted i cant type anymore it in".

Two symptoms, one line. The submit handler builds its request like this:

    asked.disabled = true;
    askWhat.textContent = 'Asking for that change...';
    fetch('/api/aiuibuilder/' + slug + '/enhance', {
      method: 'POST',
      headers: authHeaders(),        <-- not in scope here
      ...
    }).then(...).catch(function (err) { asked.disabled = false; ... });

`authHeaders` is declared INSIDE `createIntegrationsModal` (line 723 to 1436
when this was written). Every one of these call sites is outside it, so the
name is not defined there and evaluating it raises a ReferenceError.

It is raised while building fetch's ARGUMENTS, before fetch is called, so:

  - no request is ever sent            -> "it didnt do anything"
  - no promise exists, so `.catch` never runs, so `asked.disabled` is never
    put back                           -> "once i submitted i cant type
                                          anymore it in"

The same mistake is in the appearance panel's three calls, which is why that
panel says "Reading this app..." and stays there.

The function that IS reachable is `aiuiAuthHeaders`, and its own comment says
exactly why it exists:

    Mirrors authHeaders() inside createIntegrationsModal above, which is out
    of reach from here: that copy is scoped inside a different top-level
    function, not on window.

So this is not a subtle bug. It is a documented hazard walked into four
times, and nothing checked. These tests check.
"""
import os
import re

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _strip(line):
    """The line with strings and line comments removed.

    Brace counting has to ignore a `{` that is inside a string or a comment,
    or the span it measures is wrong and every test built on it is wrong in
    a way that still looks green.
    """
    line = re.sub(r"'(?:\\.|[^'\\])*'", "''", line)
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    return re.sub(r"//.*$", "", line)


def _span(name):
    """(first_line, last_line) of a top-level function, 1-indexed inclusive."""
    lines = _js().split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith("  function " + name + "("):
            start = i
            break
    assert start is not None, name + " is not a top-level function any more"

    depth = 0
    opened = False
    for i in range(start, len(lines)):
        for ch in _strip(lines[i]):
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return start + 1, i + 1
    raise AssertionError(name + " never closes")


def _calls(fn_name):
    """Every 1-indexed line calling fn_name, ignoring longer names.

    `authHeaders(` matches inside `aiuiAuthHeaders(` as plain text, and those
    are the calls that are CORRECT, so a loose search would report the fix as
    the bug.
    """
    hits = []
    for i, line in enumerate(_js().split("\n"), start=1):
        if re.search(r"(?<![A-Za-z0-9_])" + fn_name + r"\s*\(", _strip(line)):
            hits.append(i)
    return hits


# --- the bug itself -------------------------------------------------------

def test_the_modals_own_auth_headers_is_never_called_from_outside_it():
    """The whole bug, as one rule.

    `authHeaders` is a local of createIntegrationsModal. Calling it anywhere
    else is a ReferenceError at the moment somebody presses the button, which
    is the worst time to find out.
    """
    first, last = _span("createIntegrationsModal")
    outside = [n for n in _calls("authHeaders")
               if not (first <= n <= last)]
    assert outside == [], (
        "authHeaders() is called from outside createIntegrationsModal "
        "(lines %s). It is not in scope there: use aiuiAuthHeaders()."
        % outside)


def test_the_declaration_is_still_where_this_test_thinks_it_is():
    """Guards the guard. If authHeaders moves to the top level this whole
    file is measuring nothing, and would pass forever."""
    first, last = _span("createIntegrationsModal")
    declared = [n for n, line in enumerate(_js().split("\n"), start=1)
                if line.strip().startswith("function authHeaders(")]
    assert declared, "authHeaders is gone; this file needs rewriting"
    for n in declared:
        assert first <= n <= last, (
            "authHeaders now lives outside createIntegrationsModal, so the "
            "scope rule this file checks no longer applies")


# --- the four places that pressed it ---------------------------------------

def _body(first, last):
    return "\n".join(_js().split("\n")[first - 1:last])


def test_the_pencil_asks_for_the_change_with_headers_it_can_reach():
    """Ralph's actual click: point at the rating, say what to change."""
    body = _body(*_span("aiuiShowAppInline"))
    assert "/enhance'" in body, "the enhance call moved; find it and re-check"
    assert "aiuiAuthHeaders()" in body
    assert not re.search(r"(?<![A-Za-z0-9_])authHeaders\s*\(", _strip(body))


def test_the_appearance_panel_reads_and_writes_with_headers_it_can_reach():
    """Same bug, three more calls: read the theme, save it, upgrade it.

    Nobody reported this one, because the panel fails by saying "Reading
    this app..." forever rather than by saying anything wrong.
    """
    body = _body(*_span("aiuiAppearance"))
    assert "/theme" in body
    assert not re.search(r"(?<![A-Za-z0-9_])authHeaders\s*\(", _strip(body))
    assert body.count("aiuiAuthHeaders()") >= 3, (
        "the theme read, the save and the upgrade each need headers")


# --- the box has to come back ---------------------------------------------

def test_the_box_is_given_back_once_the_change_has_been_sent():
    """The success path disables the box and then hides the whole panel.

    Re-opening the pencil shows that same input again, so if nothing ever
    re-enables it, a change that WORKED still leaves a dead box behind.
    That is the second half of what Ralph hit.
    """
    body = _body(*_span("aiuiShowAppInline"))
    stop = body[body.index("function annotateStop"):]
    stop = stop[:stop.index("\n    }") + 6]
    assert "asked.disabled = false" in stop, (
        "annotateStop hides the panel but leaves the input disabled")


def test_a_change_that_throws_on_the_way_out_still_hands_the_box_back():
    """Defence for the next time, not for this bug.

    A `.catch` cannot catch a throw raised while the arguments are still
    being built: there is no promise yet. So the one thing that must not
    depend on the request being well formed is giving the person their
    input back.
    """
    body = _body(*_span("aiuiShowAppInline"))
    send = body[body.index("asked.addEventListener('keydown'"):]
    send = send[:send.index("// Appearance:")]
    assert "try {" in send and "catch" in send, (
        "the send is not wrapped, so a synchronous throw kills the box "
        "silently, which is exactly what happened on 2026-11-12")
    tail = send[send.index("catch"):]
    assert "asked.disabled = false" in tail


# --- what it still has to do ----------------------------------------------

def test_the_change_is_still_sent_to_the_user_scoped_builder():
    """Unchanged by the fix, and the reason /api/tasks/enhance is wrong: it
    is admin-only and keyed by a task id."""
    body = _body(*_span("aiuiShowAppInline"))
    assert "/api/aiuibuilder/" in body


def test_the_change_still_carries_what_was_pointed_at():
    body = _body(*_span("aiuiShowAppInline"))
    assert "aiuiAnnotatePrompt(picked, said)" in body


# --- the whole class, not just this one -----------------------------------

def test_every_aiui_function_the_preview_calls_really_exists():
    """The general form of the bug, and the cheap half of a browser.

    `node --check` is a PARSE. A name that is not in scope is a runtime
    fact, so it says nothing about any of this, and the one real browser
    test covering the appearance panel was green throughout because its
    harness supplied the missing name itself.

    Every `aiuiSomething(` called from the preview's own code must be a
    top-level function in this file. Top level is the IIFE's scope, which
    is the only scope all of this shares.
    """
    src = _js()
    defined = set(re.findall(r"^  function (aiui\w+)\(", src, re.M))
    assert len(defined) > 40, "the top-level scan found almost nothing"

    for fn in ("aiuiShowAppInline", "aiuiAppearance", "aiuiAnnotateOn",
               "aiuiSizeHandle", "aiuiSplitOpen", "aiuiSplitClose"):
        body = _body(*_span(fn))
        called = set(re.findall(r"(?<![A-Za-z0-9_.])(aiui\w+)\s*\(",
                                _strip(body)))
        # Names declared inside this function are its own business.
        local = set(re.findall(r"function (aiui\w+)\(", body))
        missing = sorted(called - defined - local)
        assert missing == [], (
            "%s calls %s, which is not a top-level function here"
            % (fn, ", ".join(missing)))
