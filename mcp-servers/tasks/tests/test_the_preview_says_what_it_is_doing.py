"""The build view names the step, not just "Building".

Ralph, 2026-11-04: "They want visual not link users need visual.. okay so
we need to let them see it how everything works".

The build view this embeds already had the visual part: a progress bar, a
live log, a spinner. What it could not say was what the build was
actually DOING. PHASE_LABELS turns a status into a word and the status is
"running" for the whole build, so the chip read "Building" for five
minutes while the thing moved through a baseline, the agent, a browser
check, fix passes, a README and a commit.

build_step_said is the build's own name for the step it is on, written by
routes_execution and phrased for the person who asked for a website.
"""
import os
import re

import pytest

PREVIEW = os.path.join(os.path.dirname(__file__), "..", "static",
                       "preview.html")


def _page():
    with open(PREVIEW, encoding="utf-8") as fh:
        return fh.read()


def test_the_chip_says_the_step_the_build_is_on():
    assert "task.build_step_said" in _page()


def test_the_status_word_is_still_the_fallback():
    """A build between steps, or one that predates this, still has to say
    something. An empty chip reads as nothing happening."""
    src = _page()
    hit = re.search(r"task\.build_step_said[^;]*PHASE_LABELS\[task\.status\]",
                    src, re.S)
    assert hit, "the status label is no longer the fallback"


def test_an_empty_step_does_not_win_over_the_fallback():
    """build_step is NULL on an older build and "" between steps. Without
    the trim, a string of spaces would beat the fallback and show a blank
    chip."""
    src = _page()
    assert re.search(r"\(task\.build_step_said \|\| \"\"\)\.trim\(\)", src)


def test_the_wording_is_the_servers_not_a_second_copy():
    """build_progress.py holds the sentences and a test there pins them as
    sentences rather than function names. A copy here would be a second
    place to change and a second thing to get out of step."""
    src = _page()
    from build_progress import STEPS
    for said in STEPS.values():
        assert said not in src, (
            "the step wording is duplicated into the page: " + said)


def test_the_steps_are_still_written_in_a_persons_words():
    """The chip shows these directly now, so they are read by somebody who
    asked for a website, not by us."""
    from build_progress import STEPS
    for key, said in STEPS.items():
        assert said[0].isupper(), key
        assert "_" not in said, key
        assert said.lower() != key, key
