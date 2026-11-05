"""A build shows every step and how far along it is.

The line under a reply said one thing: "Writing the code. 2 min so far."
That is the step, and nothing about how much of the job is behind it or
still to come.

Reference: ChatGPT's website-creation panel, numbered steps each with
their own state and a bar across the bottom.

The server half is tested for real. The page half is structural, because
integrations-ui.js is vanilla JS served as a static asset with no
harness, the same compromise as the other tests of that file.
"""
import os
import re

import pytest

import build_progress as bp

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")
ROUTES = os.path.join(os.path.dirname(__file__), "..", "routes_tasks.py")


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    src = _js()
    start = src.index("function " + name)
    ends = [src.find(m, start + 10)
            for m in ("\n  function ", "\n  // ===== End")]
    return src[start:min(e for e in ends if e != -1)]


# --- the walk itself -------------------------------------------------------

def test_every_step_is_either_on_the_walk_or_named_as_off_it():
    """A step added to STEPS and forgotten here would never be drawn, and
    nothing else would notice."""
    stray = set(bp.STEPS) - set(bp.ORDER) - set(bp.OUT_OF_BAND)
    assert not stray, stray


def test_the_walk_is_in_the_order_the_pipeline_runs_it():
    """Out of order, a build would appear to go backwards."""
    assert bp.ORDER == ("baseline", "building", "smoke", "autofix",
                        "docs", "commit")


def test_rolling_back_is_not_a_stage_on_the_way_to_an_app():
    """Showing "guard" among the steps still to come would promise every
    build a rollback."""
    assert "guard" in bp.OUT_OF_BAND
    assert "guard" not in bp.ORDER
    assert bp.reached("guard") == -1


def test_a_step_nobody_knows_is_not_placed_on_the_walk():
    assert bp.reached("") == -1
    assert bp.reached("nonsense") == -1


def test_the_walk_carries_the_wording_with_it():
    steps = bp.steps_in_order()
    assert [s["key"] for s in steps] == list(bp.ORDER)
    for s in steps:
        assert s["said"] == bp.STEPS[s["key"]]


# --- serving it ------------------------------------------------------------

def test_the_page_is_served_the_steps_rather_than_keeping_a_copy():
    """Two places already show a step to somebody. A third copy of these
    sentences is a third place to change and a third to fall out of step
    with the pipeline that writes them."""
    src = _js()
    for said in bp.STEPS.values():
        assert said not in src, "step wording copied into the page: " + said
    assert "/api/tasks/build-steps" in src


def test_the_route_is_declared_before_the_one_that_eats_it():
    """FastAPI matches in declaration order. Below /{task_id}, the path
    "build-steps" is parsed as a UUID and answers 422."""
    with open(ROUTES, encoding="utf-8") as fh:
        src = fh.read()
    assert (src.index('@router.get("/build-steps")')
            < src.index('@router.get("/{task_id}"'))


def test_the_steps_are_fetched_once():
    """The watcher polls every ten seconds for the length of a build. The
    labels do not change between those polls."""
    body = _fn("aiuiLoadSteps")
    assert "aiuiStepsAsked" in body
    assert "if (aiuiStepsAsked) return" in body


# --- what each step says ---------------------------------------------------

def test_before_is_done_on_is_working_after_is_waiting():
    steps = [{"key": k, "said": k} for k in bp.ORDER]
    src = _js()
    assert "i < now) ? 'done' : (i === now ? 'working' : 'waiting')" in src


def test_a_skipped_step_reads_as_done_rather_than_stuck():
    """autofix only runs when the browser check found something, and the
    row carries only the step it is ON. "Done" for a step that was not
    needed is a small lie; "waiting" while the build is three steps
    further on is a confusing one. The comment records the trade."""
    # The comment sits ABOVE the function, which is where a JS file puts
    # it, so the function slice does not contain it.
    src = _js()
    at = src.index("function aiuiStepStates")
    before = src[max(0, at - 900):at]
    assert "skipped" in before.lower()
    assert "autofix" in before.lower()


def test_an_unknown_step_leaves_the_walk_alone():
    """A build on "guard" is not at step 0. Treating it as the first step
    would redraw a finished walk as barely started."""
    src = _js()
    assert "var now = -1;" in src
    assert "if (now >= 0)" in src


# --- what the rows actually come out as ----------------------------------
#
# Run through node, not read. Every test above this point asserts the
# SOURCE of aiuiStepStates, and on 2026-11-05 all of them passed while a
# build one minute in showed six rows of "Waiting", which is what Ralph
# saw and is the opposite of what this panel is for.

def _states(at):
    import json
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = _js()
    start = src.index("  function aiuiStepStates(")
    end = src.index("\n  function ", start + 10)
    steps = json.dumps([{"key": k, "said": k} for k in bp.ORDER])
    script = (src[start:end] + "\nconsole.log(JSON.stringify("
              "aiuiStepStates(" + steps + ", " + json.dumps(at) + ")"
              ".map(function (r) { return r.state; })));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-600:]
    return json.loads(out.stdout.strip())


def test_a_build_that_has_not_said_anything_yet_is_on_its_first_step():
    """A running build that has not reported a step is still running, and
    it is running the first one. Six rows of "Waiting" a minute in reads
    as a panel that is broken, and it was: every row said nothing was
    happening while the agent was working."""
    states = _states("")
    assert states[0] == "working"
    assert set(states[1:]) == {"waiting"}


def test_a_step_it_has_reported_marks_everything_before_it_done():
    states = _states("smoke")
    at = bp.ORDER.index("smoke")
    assert states[at] == "working"
    assert set(states[:at]) == {"done"}
    assert set(states[at + 1:]) == {"waiting"}


def test_the_last_step_leaves_nothing_waiting():
    states = _states(bp.ORDER[-1])
    assert states[-1] == "working"
    assert "waiting" not in states


@pytest.mark.parametrize("out_of_band", list(bp.OUT_OF_BAND))
def test_a_step_off_the_path_claims_no_progress_at_all(out_of_band):
    """A build on "guard" is rolling back, near the END of its walk.
    Showing step one as working there would be a guess dressed up as
    progress, and it is the reason the empty case is handled by itself
    rather than by "anything we cannot place"."""
    assert set(_states(out_of_band)) == {"waiting"}


def test_an_out_of_band_step_is_said_underneath():
    body = _fn("aiuiStepPanel")
    assert "!known && said" in body


# --- not going quiet -------------------------------------------------------

def test_the_sentence_is_still_there_when_the_list_is_not():
    """A build must never go quiet because a list of labels could not be
    fetched."""
    src = _js()
    assert "aiuiStepPanel(chatId, task, mins)" in src
    # The CALL, not the sentence. The sentence survives inside code that
    # can no longer run, so checking for it passed with the fallback
    # switched off.
    assert "aiuiBuildLine(chatId, step" in src
    assert "Still building, " in src


def test_the_list_goes_away_when_the_build_settles():
    src = _js()
    # Once to define it and TWICE to call it: when the build settles, and
    # when the watcher gives up. "at least two" passed with one call site
    # deleted, because the definition counts towards it.
    assert src.count("aiuiClearSteps()") == 3
    assert "aiuiHideBuildInline(id);" in src
    settled = src.index("aiuiHideBuildInline(id);")
    assert "aiuiClearSteps()" in src[settled:settled + 120]


def test_the_sentences_are_escaped_on_the_way_in():
    """Ours and fixed today, and they reach innerHTML. "Ours today" is how
    an escaping hole starts."""
    body = _fn("aiuiStepPanel")
    assert "aiuiEscape(s.said)" in body
    esc = _fn("aiuiEscape")
    for ch in ("&amp;", "&lt;", "&gt;", "&quot;"):
        assert ch in esc


# --- one view of a running build, not two --------------------------------

def test_the_embedded_build_page_is_not_shown_beside_the_list():
    """Both say the same thing. Showing both gave a reply a numbered list
    under a tall panel whose preview area is empty for the whole build,
    which is what Ralph was looking at when he asked for the interface to
    be clean."""
    src = _js()
    poll = src[src.index("function aiuiPollBuild("):]
    poll = poll[:poll.index("\n  }\n")]
    drawn = poll.index("aiuiShowBuildInline(chatId, id);")
    panel = poll.index("if (aiuiStepPanel(chatId, task, mins)) {")
    assert panel < drawn, (
        "the embedded build page is drawn before the list is tried, so "
        "both are always on screen")
    assert "aiuiHideBuildInline(id);" in poll[panel:drawn]


def test_the_embedded_build_page_survives_as_the_fallback():
    """A build must never go quiet because a list of labels could not be
    fetched, so the old panel stays for exactly that case."""
    src = _js()
    poll = src[src.index("function aiuiPollBuild("):]
    poll = poll[:poll.index("\n  }\n")]
    # Once, and after the list has been tried and declined.
    assert poll.count("aiuiShowBuildInline(chatId, id);") == 1
