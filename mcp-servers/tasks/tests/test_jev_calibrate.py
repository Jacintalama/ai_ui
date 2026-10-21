"""The pure half of scripts/jev_calibrate.py: what one Jev answer would have
done at a given cut-off, and the count per cut-off. The live half calls
TypeSafe and is run by hand in the container."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import jev_calibrate as c  # noqa: E402

ANSWER_DEV = {"roster": "small", "message": "the login button does nothing",
              "kind": "answer", "who": {"Dev"}}
JOB = {"roster": "small", "message": "plan the launch end to end",
       "kind": "job", "who": set()}


def test_a_sure_right_pick_is_right():
    assert c.outcome(ANSWER_DEV, "answer", 0.9, "Dev", 0.9, 0.8) == "right"


def test_a_sure_pick_of_another_agent_is_wrong():
    assert c.outcome(ANSWER_DEV, "answer", 0.9, "Mia", 0.9, 0.8) == "wrong"


def test_a_job_handed_to_one_agent_is_wrong():
    assert c.outcome(JOB, "answer", 0.9, "Dev", 0.9, 0.8) == "wrong"


@pytest.mark.parametrize("kind, kc, wc", [("answer", 0.7, 0.9),
                                          ("answer", 0.9, 0.7),
                                          ("job", 0.99, 0.99)])
def test_anything_short_of_a_sure_answer_falls_back(kind, kc, wc):
    assert c.outcome(ANSWER_DEV, kind, kc, "Dev", wc, 0.8) == "fallback"


def test_the_cut_off_is_inclusive():
    assert c.outcome(ANSWER_DEV, "answer", 0.8, "Dev", 0.8, 0.8) == "right"


def test_the_table_counts_each_cut_off():
    rows = [(ANSWER_DEV, "answer", 0.95, "Dev", 0.9),
            (ANSWER_DEV, "answer", 0.95, "Mia", 0.7),
            (JOB, "job", 0.8, "Ada", 0.5)]
    got = c.table(rows, [0.6, 0.8])
    assert got[0.6] == {"right": 1, "wrong": 1, "fallback": 1}
    assert got[0.8] == {"right": 1, "wrong": 0, "fallback": 2}


def test_every_case_names_only_agents_on_its_roster():
    for case in c.CASES:
        names = {a["name"] for a in c.ROSTERS[case["roster"]]}
        assert case["kind"] in ("answer", "job")
        assert case["who"] <= names, case["message"]
        assert bool(case["who"]) == (case["kind"] == "answer"), case["message"]


def test_no_case_names_an_agent_in_the_message():
    """A named agent never reaches Jev in the room (agent_routing), so a case
    that names one measures a message Jev is never asked about."""
    for case in c.CASES:
        names = {a["name"].lower() for a in c.ROSTERS[case["roster"]]}
        words = {w.strip(",.?!").lower() for w in case["message"].split()}
        assert not names & words, case["message"]


def test_every_case_is_a_message_the_round_puts_to_jev():
    """Measured by the round's own routing, not by eye: a case that routes
    as named, a meeting or too short would never reach Jev."""
    import agent_routing
    import routes_agent_chat as r
    for case in c.CASES:
        why = agent_routing.choose_speakers(case["message"],
                                            c.ROSTERS[case["roster"]])[2]
        assert why in r.TEAM_ROUTES, (why, case["message"])
        assert why != agent_routing.ROUTE_MEETING, case["message"]
        assert len(case["message"].split()) >= r.MIN_TRIAGE_WORDS


async def test_the_run_stops_at_the_spend_cap(monkeypatch):
    calls = []

    async def post(body, key):
        calls.append(body)
        return {"answers": {"kind": {"choice": "answer", "confidence": 0.9},
                            "who": {"choice": "Dev", "confidence": 0.9}},
                "usage": {"input_tokens": 1_000_000}}

    monkeypatch.setattr(c.agent_decider, "_post", post)
    rows, spent = await c.run(c.CASES, key="k", cap_usd=0.05)
    # $0.042 per call: the second call would pass the cap, so it is not made.
    assert len(calls) == 1 and len(rows) == 1
    assert spent == pytest.approx(0.042)
