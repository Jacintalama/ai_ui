"""The calibration of Jev's small checks (scripts/jev_checks_calibrate.py).

The scoring and the choice rule are pure and tested here. So is the thing
that makes the measurement mean anything: every labelled case is one the
gate in front of its check would actually let through to Jev.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import agent_escalation  # noqa: E402
import agent_jev  # noqa: E402
import agent_memory  # noqa: E402
import agent_routing  # noqa: E402
import jev_checks_calibrate as cal  # noqa: E402
import routes_agent_turn  # noqa: E402
from rollback_pick import choose_rollback_target, wants_before  # noqa: E402


# --- the cases reach Jev in production --------------------------------------

@pytest.mark.parametrize("text,label", cal.PLAIN)
def test_each_plain_case_is_one_the_paid_move_asks_about(text, label):
    assert label in agent_jev.PLAIN_CRITERIA
    intent = agent_escalation.Intent(person_text=text)
    assert agent_escalation.needs_plain_check(intent, True), text


@pytest.mark.parametrize("user,answer,label", cal.REFLECT)
def test_each_reflect_case_is_one_that_would_be_reflected_on(user, answer,
                                                             label):
    assert agent_memory.should_reflect(user, answer), user


@pytest.mark.parametrize("text,label", cal.RELEASE)
def test_each_release_case_is_one_the_release_check_reads(text, label):
    assert 0 < len(text.split()) <= routes_agent_turn.RELEASE_MAX_WORDS
    # The exact phrases are released without asking Jev.
    assert not agent_routing.wants_release(text), text


@pytest.mark.parametrize("phrase,label", cal.ROLLBACK)
def test_each_rollback_case_is_one_the_rules_hand_on(phrase, label):
    assert wants_before(phrase)
    assert choose_rollback_target(cal.HISTORY, phrase,
                                  slug="shop").needs_user_choice, phrase
    assert label in {v["short_sha"] for v in cal.HISTORY}


def test_every_check_has_cases_on_both_sides():
    labels = {}
    for purpose, label, _ in cal.requests():
        labels.setdefault(purpose, set()).add(str(label))
    assert set(labels) == set(cal.SHAPES)
    for purpose, seen in labels.items():
        assert len(seen) >= 2, purpose


def test_the_requests_are_the_ones_production_builds():
    for purpose, _, (state, question) in cal.requests():
        assert isinstance(state, str) and state
        assert question["type"] in ("choice", "noul")


# --- scoring ----------------------------------------------------------------

@pytest.mark.parametrize("shape,label,choice,value,cut,expected", [
    ("choice", "work", "work", 0.9, 0.8, "right"),
    ("choice", "work", "plain", 0.9, 0.8, "wrong"),
    ("choice", "work", "plain", 0.7, 0.8, "fallback"),
    ("yes", True, None, 0.9, 0.8, "right"),
    ("yes", False, None, 0.9, 0.8, "wrong"),
    ("yes", False, None, 0.5, 0.8, "fallback"),
    ("no", False, None, 0.1, 0.3, "right"),
    ("no", True, None, 0.2, 0.3, "wrong"),
    ("no", True, None, 0.6, 0.3, "fallback"),
])
def test_outcome(shape, label, choice, value, cut, expected):
    assert cal.outcome(shape, label, choice, value, cut) == expected


def test_table_counts_per_cut():
    rows = [(True, None, 0.95), (False, None, 0.85), (False, None, 0.2)]
    t = cal.table("yes", rows, [0.8, 0.9])
    assert t[0.8] == {"right": 1, "wrong": 1, "fallback": 1}
    assert t[0.9] == {"right": 1, "wrong": 0, "fallback": 2}


# --- the rule fixed before the runs -----------------------------------------

def _t(cuts, wrong_at):
    return {c: {"right": 1, "wrong": 1 if c in wrong_at else 0,
                "fallback": 0} for c in cuts}


def test_up_takes_the_lowest_clean_cut_plus_one_step():
    tables = [_t(cal.UP, {0.5, 0.6}), _t(cal.UP, {0.5, 0.6, 0.7})]
    assert cal.choose("yes", tables) == 0.8         # clean from 0.75, +1


def test_up_never_goes_past_the_top():
    tables = [_t(cal.UP, set(cal.UP) - {0.9})]
    assert cal.choose("choice", tables) == 0.9


def test_down_takes_the_highest_clean_cut_minus_one_step():
    tables = [_t(cal.DOWN, {0.4}), _t(cal.DOWN, {0.4})]
    assert cal.choose("no", tables) == 0.2          # clean from 0.3, -1


def test_no_clean_cut_switches_the_check_off():
    assert cal.choose("yes", [_t(cal.UP, set(cal.UP))]) > 1
    assert cal.choose("no", [_t(cal.DOWN, set(cal.DOWN))]) < 0


def test_an_off_cut_never_acts():
    for shape in ("yes", "choice"):
        assert cal.outcome(shape, True, True, 1.0,
                           cal.OFF["up"]) == "fallback"
    assert cal.outcome("no", False, None, 0.0, cal.OFF["down"]) == "fallback"


# --- the spend cap ----------------------------------------------------------

def test_the_run_stops_at_the_cap(monkeypatch):
    calls = []

    async def post(body, key):
        calls.append(body)
        return {"model": "jev-1.13.0",
                "answers": {"q": {"type": "noul", "noul": 0.5}},
                "usage": {"input_tokens": 1_000_000}}     # $0.042 a call

    monkeypatch.setattr(cal.agent_decider, "_post", post)
    # The third call would make $0.126, past the cap: two are made.
    rows, spent = asyncio.run(cal.run(cal.requests(), "k", cap_usd=0.09))
    assert len(calls) == 2 and spent == pytest.approx(0.084)


# --- the main chat's tool pick (2026-10-27) ---------------------------------
# A missed tool breaks the answer; an extra one costs a few tokens. So the
# cut is the highest with no misses, one step lower, never below 0.5.

def test_every_tool_case_names_tools_the_pick_offers():
    for text, needed, ok in cal.TOOL_CASES:
        assert set(needed) <= set(cal.TOOLS) and set(ok) <= set(cal.TOOLS), text
        assert not set(needed) & set(ok), text


def test_every_tool_case_reaches_the_assistant():
    """Not a greeting, and no agent's name: those never get a tool pick.

    Asked by the words rather than by a word count since 2026-10-29. The
    count was the point of this check and also its blind spot: a calibration
    case may now be three words long, because "check my inbox" is a real
    request and used to be gated out as if it were "hello there".
    """
    for text, _, _ in cal.TOOL_CASES:
        assert not routes_agent_turn.is_small_talk(text), text


def test_tool_scores_count_misses_and_extras():
    values = {"calendar": 0.9, "gmail": 0.7, "code": 0.4}
    assert cal.tool_score(values, {"calendar"}, {"code"}, 0.6) == (0, 1)
    assert cal.tool_score(values, {"calendar", "code"}, set(), 0.6) == (1, 1)
    assert cal.tool_score(values, set(), set(), 0.95) == (0, 0)


def test_the_tool_cut_is_the_highest_with_no_misses_one_step_down():
    misses = [{0.5: 0, 0.6: 0, 0.7: 0, 0.75: 0, 0.8: 1, 0.85: 2, 0.9: 3},
              {0.5: 0, 0.6: 0, 0.7: 1, 0.75: 1, 0.8: 1, 0.85: 2, 0.9: 3}]
    assert cal.choose_tool_cut(misses) == 0.5           # clean to 0.6, -1


def test_no_clean_tool_cut_switches_the_pick_off():
    misses = [{c: 1 for c in cal.UP}]
    assert cal.choose_tool_cut(misses) < 0
