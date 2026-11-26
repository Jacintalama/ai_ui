"""Save as your skill: what counts as something made."""
import json

import pytest

import agent_activity
import skill_offer

OK = json.dumps({"ok": True, "item": {"id": "w1"}})
BAD = json.dumps({"ok": False, "error": "n8n refused it"})


@pytest.mark.parametrize("tool", ["my-n8n_create_workflow", "create_workflow",
                                  "my-n8n_activate_workflow"])
def test_a_workflow_that_was_made_counts(tool):
    assert skill_offer.counts(tool, agent_activity.STEP_OK, OK)


def test_a_refused_or_failed_workflow_does_not_count():
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, BAD)
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_FAILED, OK)
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, "not json")
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, "[1]")
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, None)


def test_an_automation_counts_only_when_it_was_made():
    assert skill_offer.counts("create_automation", agent_activity.STEP_OK,
                              "Made the automation Leads. Ada will do that ...")
    assert not skill_offer.counts("create_automation", agent_activity.STEP_OK,
                                  "Nothing was made: name taken")


def test_other_tools_never_count():
    for t in ("my-n8n_list_my_workflows", "my-n8n_update_workflow",
              "my-n8n_deactivate_workflow", "create_schedule", "send_email"):
        assert not skill_offer.counts(t, agent_activity.STEP_OK, OK)


def test_note_collects_only_inside_collecting():
    skill_offer.note("create_workflow", agent_activity.STEP_OK, OK)   # no error
    with skill_offer.collecting() as made:
        skill_offer.note("create_workflow", agent_activity.STEP_OK, OK)
        skill_offer.note("send_email", agent_activity.STEP_OK, OK)
        skill_offer.note(None, None, None)
    assert made == ["create_workflow"]


def test_the_link_is_added_once():
    once = skill_offer.with_link("Done.")
    assert once == "Done.\n\n" + skill_offer.LINK
    assert skill_offer.with_link(once) == once
