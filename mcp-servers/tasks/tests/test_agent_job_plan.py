"""Reading the plan the lead agent wrote, and choosing the lead.

Pure: no model, no database. Every rejection here means the round runs as it
does today, so the tests that matter most are the ones that say "None".
"""
import json

import agent_job_plan as plan

ROSTER = [
    {"id": "agent-mia", "name": "Mia", "meta": {"role": "Researcher"}},
    {"id": "agent-ada", "name": "Ada", "meta": {"role": "Analyst"}},
    {"id": "agent-dev", "name": "Dev", "meta": {"role": "Developer"}},
]

GOOD = {"kind": "job", "steps": [
    {"agent": "Mia", "do": "Find the three latest reports."},
    {"agent": "Ada", "do": "Compare them."},
    {"agent": "Dev", "do": "Draft a one page summary."}]}

EXPECTED = [{"agent_id": "agent-mia", "task": "Find the three latest reports."},
            {"agent_id": "agent-ada", "task": "Compare them."},
            {"agent_id": "agent-dev", "task": "Draft a one page summary."}]


def _job(*steps):
    return json.dumps({"kind": "job",
                       "steps": [{"agent": a, "do": d} for a, d in steps]})


def test_a_good_plan_becomes_steps():
    assert plan.parse_triage(json.dumps(GOOD), ROSTER) == EXPECTED


def test_a_fenced_plan_is_read():
    text = "```json\n%s\n```" % json.dumps(GOOD, indent=2)
    assert plan.parse_triage(text, ROSTER) == EXPECTED


def test_prose_around_the_json_is_ignored():
    text = ("Sure, here is the plan for the team: %s Let me know if it "
            "should change." % json.dumps(GOOD))
    assert plan.parse_triage(text, ROSTER) == EXPECTED


def test_braces_in_the_prose_before_the_json_do_not_stop_it():
    text = "Using {curly} notes: %s" % json.dumps(GOOD)
    assert plan.parse_triage(text, ROSTER) == EXPECTED


def test_answer_means_no_job():
    assert plan.parse_triage('{"kind": "answer"}', ROSTER) is None


def test_an_unknown_agent_discards_the_plan():
    text = _job(("Mia", "Find them."), ("Zed", "Compare them."))
    assert plan.parse_triage(text, ROSTER) is None


def test_one_step_is_not_a_job():
    assert plan.parse_triage(_job(("Mia", "Find them.")), ROSTER) is None


def test_seven_steps_is_too_many():
    steps = [("Mia", "Step %d." % i) for i in range(7)]
    assert plan.parse_triage(_job(*steps), ROSTER) is None


def test_six_steps_is_allowed():
    steps = [("Mia", "Step %d." % i) for i in range(6)]
    assert len(plan.parse_triage(_job(*steps), ROSTER)) == 6


def test_an_empty_task_discards_the_plan():
    text = _job(("Mia", "Find them."), ("Ada", "   "))
    assert plan.parse_triage(text, ROSTER) is None


def test_a_missing_task_discards_the_plan():
    text = json.dumps({"kind": "job", "steps": [
        {"agent": "Mia", "do": "Find them."}, {"agent": "Ada"}]})
    assert plan.parse_triage(text, ROSTER) is None


def test_not_json_at_all():
    assert plan.parse_triage("I think Mia should look first.", ROSTER) is None
    assert plan.parse_triage("", ROSTER) is None
    assert plan.parse_triage(None, ROSTER) is None
    assert plan.parse_triage('{"kind": "job", "steps": [', ROSTER) is None


def test_steps_of_the_wrong_shape():
    for steps in ("Mia then Ada", None, [["Mia", "x"], ["Ada", "y"]]):
        text = json.dumps({"kind": "job", "steps": steps})
        assert plan.parse_triage(text, ROSTER) is None, steps


def test_names_in_another_case_still_match():
    text = _job(("mia", "Find them."), (" ADA ", "Compare them."))
    assert plan.parse_triage(text, ROSTER) == [
        {"agent_id": "agent-mia", "task": "Find them."},
        {"agent_id": "agent-ada", "task": "Compare them."}]


def test_names_match_the_roster_names_only():
    # An id or a role is not a name: matching them would let a plan reach an
    # agent the lead never named.
    text = _job(("agent-mia", "Find them."), ("Analyst", "Compare them."))
    assert plan.parse_triage(text, ROSTER) is None


def test_two_agents_with_one_name_are_ambiguous():
    roster = ROSTER + [{"id": "agent-mia-2", "name": "mia", "meta": {}}]
    text = _job(("Mia", "Find them."), ("Ada", "Compare them."))
    assert plan.parse_triage(text, roster) is None


def test_a_long_task_is_cut_not_rejected():
    text = _job(("Mia", "x" * 500), ("Ada", "Compare them."))
    steps = plan.parse_triage(text, ROSTER)
    assert len(steps[0]["task"]) == plan.TASK_MAX_CHARS == 300


def test_a_roster_with_bad_rows_still_matches_the_good_ones():
    roster = [None, "Mia", {"id": "x"}, {"name": "NoId"}] + ROSTER
    assert plan.parse_triage(json.dumps(GOOD), roster) == EXPECTED


def test_the_team_lead_switch_wins():
    roster = [{"id": "a", "name": "Pat", "meta": {"role": "Project manager"}},
              {"id": "b", "name": "Lee", "meta": {"team_lead": True}}]
    assert plan.choose_lead(roster)["id"] == "b"


def test_a_manager_role_leads_when_nobody_is_marked():
    for role in ("Project Manager", "Team lead", "Coordinator",
                 "project planner"):
        roster = [{"id": "a", "name": "Mia", "meta": {"role": "Researcher"}},
                  {"id": "b", "name": "Pat", "meta": {"role": role}}]
        assert plan.choose_lead(roster)["id"] == "b", role


def test_otherwise_the_first_agent_leads():
    assert plan.choose_lead(ROSTER)["id"] == "agent-mia"
    assert plan.choose_lead([{"id": "a", "name": "A"}])["id"] == "a"


def test_no_agents_no_lead():
    assert plan.choose_lead([]) is None
    assert plan.choose_lead(None) is None
