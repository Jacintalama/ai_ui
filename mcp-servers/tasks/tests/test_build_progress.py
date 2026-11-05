"""A build says which step it is on.

The main chat has watched builds since 2026-11-03 and could only count
minutes at them:

    Still building, 4 min so far.

A timer is not progress. It says the thing is alive and nothing about
whether it is nearly done, stuck on a browser check, or rolling back a
change that broke the app. The build has always known: _run_execution runs
named steps in order and has since it was written, and nothing carried the
name out of the process.

Two rules hold this together and both are tested, because both are the
kind that rot quietly.
"""
import inspect

import pytest

import build_progress as B
import routes_execution


# --- the words are for the person, not for us ------------------------------

def test_every_step_reads_as_something_a_person_would_say():
    """"AutoFix pass 2" is our word for it. The person asked for a website.
    A step named after the function is a line nobody outside this repo can
    read."""
    for key, said in B.STEPS.items():
        assert said[0].isupper(), key
        assert " " in said, "%s is a label, not a sentence: %r" % (key, said)
        assert key.lower() not in said.lower().replace(" ", ""), (
            "%s just repeats its own key" % key)


def test_no_step_is_longer_than_a_line():
    """It sits under a reply in a chat, not in a log."""
    for key, said in B.STEPS.items():
        assert len(said) <= B.MAX_STEP_CHARS, key


def test_an_unknown_step_shows_itself_rather_than_nothing():
    """A step added in code and forgotten here still shows SOMETHING, which
    is how anybody notices it is missing. Showing nothing is how it stays
    missing."""
    assert B.wording("brand-new-step") == "brand-new-step"


def test_nothing_is_still_nothing():
    for empty in ("", None):
        assert B.wording(empty) == ""


# --- what the chat draws ---------------------------------------------------

def test_a_running_build_shows_its_step():
    assert B.line_for({"status": "running", "build_step": "smoke"}) == \
        B.STEPS["smoke"]


def test_a_planning_build_counts_too():
    assert B.line_for({"status": "planning", "build_step": "building"})


def test_a_finished_build_shows_nothing():
    """The watcher writes a closing message for those. A progress line
    under a finished build would contradict it."""
    for done in ("completed", "failed", "awaiting_input"):
        assert B.line_for({"status": done, "build_step": "smoke"}) == ""


def test_a_build_with_no_step_falls_back_to_what_it_did_before():
    """Every build that predates this, and any build between steps. The
    caller then counts minutes, as it always did."""
    assert B.line_for({"status": "running"}) == ""
    assert B.line_for({"status": "running", "build_step": None}) == ""


def test_rubbish_is_not_a_crash():
    for junk in (None, "", [], {"status": None}):
        B.line_for(junk)


# --- saying so must never cost the build -----------------------------------

async def test_a_write_that_fails_does_not_reach_the_build(monkeypatch):
    """A build that completes and could not say it reached the docs sweep
    is a build that completed. A build that dies because this raised is a
    progress line costing somebody their work."""
    async def boom(task_id, step):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(B, "_write_seam", boom)
    await B.say("t1", "smoke")


async def test_nothing_worth_writing_is_not_written(monkeypatch):
    called = []

    async def spy(task_id, step):
        called.append(step)

    monkeypatch.setattr(B, "_write_seam", spy)
    await B.say(None, "smoke")
    await B.say("t1", "")
    await B.say("t1", "   ")
    assert called == []


async def test_a_step_is_written_once_and_plainly(monkeypatch):
    called = []

    async def spy(task_id, step):
        called.append((task_id, step))

    monkeypatch.setattr(B, "_write_seam", spy)
    await B.say("t1", "smoke")
    assert called == [("t1", "smoke")]


# --- the build actually says it --------------------------------------------

def test_the_build_reports_each_step_it_runs():
    """The point of the whole change. Checked against the source because
    driving _run_execution needs the database tier, which does not run
    here; CLAUDE.md says to verify its wiring on the server instead."""
    import re
    from collections import Counter
    said = Counter(re.findall(r'build_progress\.say\(task_id, "([a-z]+)"\)',
                              inspect.getsource(routes_execution)))
    # Counted, not merely present. "smoke" is reported TWICE, before the
    # first browser check and again after each fix pass, so a test that
    # only asked whether the word appeared passed while one of the two
    # call sites had been deleted. That exact mutation went uncaught on
    # the first run of this test.
    expected = {"baseline": 1, "building": 1, "smoke": 2, "autofix": 1,
                "docs": 1, "commit": 1, "guard": 1}
    assert dict(said) == expected, (
        "the build reports %s, expected %s" % (dict(said), expected))


def test_every_step_the_build_reports_has_words_for_it():
    """The other direction. A step reported in code with no sentence here
    shows its own key to the person, which is better than nothing and
    worse than a sentence."""
    import re
    said = set(re.findall(r'build_progress\.say\(task_id, "([a-z]+)"\)',
                          inspect.getsource(routes_execution)))
    missing = sorted(s for s in said if s not in B.STEPS)
    assert missing == [], "reported with no wording: " + ", ".join(missing)


# --- the wording lives in ONE place ----------------------------------------

def test_the_sentence_is_computed_on_the_server():
    """The page shows whatever this says and knows none of the keys. A
    wording table in both places is one that drifts, and the half nobody
    is looking at is the half that goes stale."""
    import datetime
    import uuid
    from schemas import TaskOut
    row = TaskOut(id=uuid.uuid4(), meeting_id=uuid.uuid4(),
                  action_type="BUILD", assignee_name="R",
                  assignee_email="r@example.com", description="d",
                  priority="IMPORTANT", status="running",
                  build_step="smoke", created_at=datetime.datetime.now())
    assert row.model_dump()["build_step_said"] == B.STEPS["smoke"]


def test_a_task_with_no_step_sends_an_empty_sentence():
    import datetime
    import uuid
    from schemas import TaskOut
    row = TaskOut(id=uuid.uuid4(), meeting_id=uuid.uuid4(),
                  action_type="BUILD", assignee_name="R",
                  assignee_email="r@example.com", description="d",
                  priority="IMPORTANT", status="running",
                  created_at=datetime.datetime.now())
    assert row.model_dump()["build_step_said"] == ""


def test_the_page_shows_the_sentence_and_never_the_key():
    """Structural, because this file is vanilla JS with no harness. If the
    page ever SHOWS build_step it will print "smoke" at somebody who asked
    for a website.

    Reading the key is allowed now, and matching on it is the point: the
    step list asks which of the served steps a build is on, and that
    comparison is by key. What it draws is the sentence that came with it.

    So this asserts the key never reaches the screen, rather than that the
    page never touches it, which is what it said until the step list was
    built.
    """
    import os
    import re
    js = os.path.join(os.path.dirname(__file__), "..", "..",
                      "gdrive", "integrations-ui.js")
    with open(js, encoding="utf-8") as fh:
        src = fh.read()
    assert "build_step_said" in src
    # Line by line, because a window of characters around the match can
    # contain the very thing it is checking for: the first version of
    # this passed on `var at = ''; el.textContent = task.build_step;`,
    # since "var at =" was inside the window.
    key = re.compile(r"task\.build_step\b(?!_)")
    sinks = ("textContent", "innerHTML", "innerText", "appendChild",
             "aiuiEscape", "aiuiBuildLine")
    hits = [ln for ln in src.split(chr(10)) if key.search(ln)]
    assert hits, "nothing reads the key, so the step list cannot match"
    for ln in hits:
        assert "var at = String((task && task.build_step)" in ln, (
            "the key is read somewhere this test has not vetted: " + ln.strip())
        for sink in sinks:
            assert sink not in ln, (
                "the raw key is on its way to the screen: " + ln.strip())


def test_the_page_still_falls_back_to_minutes():
    """Every build that predates this has no step at all, and the line
    must not go blank for them."""
    import os
    js = os.path.join(os.path.dirname(__file__), "..", "..",
                      "gdrive", "integrations-ui.js")
    with open(js, encoding="utf-8") as fh:
        src = fh.read()
    assert "Still building, ' + mins" in src
