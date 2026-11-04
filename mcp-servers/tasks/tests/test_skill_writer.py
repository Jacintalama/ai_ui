"""Writing a skill for somebody who needs one.

The platform ships 68 skills and there was no way to make a sixty-ninth.
user_skills.py gave a person somewhere to keep their own; this is what
fills one in, from a sentence describing a job.

Everything that decides what the model is asked and how its answer is read
is pure, so none of this needs a model. The one network call is a seam.

What these pin down is the part that fails silently. A skill naming a tool
somebody has not connected looks right, saves, and quietly cannot do the
thing. A skill that is too long is accepted by every check except the one
that matters, which is the prompt it is pasted into on every message.
"""
import pytest

import agent_skills
import skill_writer as SW

TOOLS = {"gmail": "Gmail", "trello": "Trello"}

GOOD = """---
name: chase-invoices
description: Chase unpaid invoices. Use when an invoice is past its due date.
allowed-tools: [gmail]
---
Steps:
1. List invoices past their due date.
2. Draft one reminder per invoice.

Rules:
- Never invent an amount."""


# --- what the model is told ------------------------------------------------

def test_the_prompt_names_the_tools_this_person_has():
    """A skill that names Gmail for somebody who has not connected Gmail is
    the silent-failure case: it looks right, it saves, and the agent
    quietly cannot do the thing."""
    text = str(SW.prompt_for("chase invoices", TOOLS, 4000))
    assert "gmail (Gmail)" in text
    assert "trello (Trello)" in text


def test_somebody_with_no_tools_is_told_so_rather_than_shown_nothing():
    """An empty list reads as "I forgot to say", and the model invents
    plausible tool names to fill it."""
    text = str(SW.prompt_for("chase invoices", {}, 4000))
    assert "connected no tools" in text


def test_the_size_ceiling_is_given_as_a_number():
    """"Be concise" produces a skill that does not fit. A number produces
    one that does."""
    assert "4000" in str(SW.prompt_for("x", TOOLS, 4000))
    assert "1500" in str(SW.prompt_for("x", TOOLS, 1500))


def test_the_ceiling_passed_is_the_one_the_prompt_enforces():
    """Not asserted by the function, so asserted here."""
    assert agent_skills.MAX_SKILL_CHARS == 4000


def test_the_house_rules_are_carried():
    """These are what made the shipped skills work, measured on a real
    reply: one job per skill, steps then rules, never invent, answer and
    stop."""
    text = str(SW.prompt_for("x", TOOLS, 4000))
    for rule in ("One job per skill", "Never invent a fact",
                 "Answer and stop", "no filesystem"):
        assert rule in text


def test_an_enormous_job_description_is_cut():
    """It arrives from a person or from a model's tool call, so it is not
    bounded by anything upstream."""
    text = str(SW.prompt_for("x" * 5000, TOOLS, 4000))
    assert "x" * (SW.MAX_JOB_CHARS + 1) not in text


# --- reading the answer ----------------------------------------------------

def test_a_well_formed_skill_is_read():
    draft = SW.parse_draft(GOOD)
    assert draft["name"] == "chase-invoices"
    assert draft["description"].startswith("Chase unpaid invoices")
    assert draft["tools"] == ["gmail"]
    assert draft["body"].startswith("Steps:")
    assert "allowed-tools" not in draft["body"]


def test_a_code_fence_is_not_a_reason_to_throw_a_skill_away():
    """A model told not to use one sometimes uses one anyway. That costs
    nothing to accept and is otherwise a perfectly good skill."""
    draft = SW.parse_draft("```markdown\n" + GOOD + "\n```")
    assert draft["name"] == "chase-invoices"
    assert draft["tools"] == ["gmail"]


@pytest.mark.parametrize("written", [
    "[gmail, trello]", "gmail, trello", "[gmail,trello]",
    "\n  - gmail\n  - trello", "'gmail', 'trello'",
])
def test_the_tool_list_is_read_however_it_was_written(written):
    """The format's examples use a YAML list; models write all of these and
    they all mean the same thing."""
    text = GOOD.replace("allowed-tools: [gmail]", "allowed-tools: " + written)
    assert SW.parse_draft(text)["tools"] == ["gmail", "trello"]


def test_a_skill_with_no_tools_reads_as_none_not_as_a_blank():
    text = GOOD.replace("allowed-tools: [gmail]", "allowed-tools: []")
    assert SW.parse_draft(text)["tools"] == []


def test_a_duplicate_tool_is_named_once():
    text = GOOD.replace("allowed-tools: [gmail]", "allowed-tools: [gmail, gmail]")
    assert SW.parse_draft(text)["tools"] == ["gmail"]


def test_a_skill_with_no_frontmatter_keeps_its_instructions():
    """Half an answer is still worth showing somebody: they can name it
    themselves. Throwing it away gives them nothing to react to."""
    draft = SW.parse_draft("Steps:\n1. Do the thing.")
    assert draft["body"].startswith("Steps:")
    assert draft["name"] == ""


def test_an_unknown_frontmatter_key_is_ignored_rather_than_stored():
    text = GOOD.replace("name: chase-invoices",
                        "name: chase-invoices\nlicense: Proprietary")
    draft = SW.parse_draft(text)
    assert draft["name"] == "chase-invoices"
    assert "license" not in draft


def test_nothing_at_all_is_an_empty_draft_and_not_a_crash():
    """This runs on a model's answer. An exception here is a 500 for a
    model having a bad day."""
    for empty in ("", "   ", None, "```\n```"):
        draft = SW.parse_draft(empty)
        assert draft["body"] == "" and draft["name"] == ""


def test_rubbish_is_an_empty_draft_rather_than_an_exception():
    for junk in ("---", "---\n---", "{]", "---\nname\n---\n"):
        SW.parse_draft(junk)


# --- what is worth showing somebody ---------------------------------------

def test_a_draft_with_no_instructions_is_not_worth_showing():
    problem = SW.draft_problem({"name": "x-y", "body": "  "})
    assert "Try saying the job in a sentence" in problem


def test_a_draft_with_no_name_is_not_worth_showing():
    assert SW.draft_problem({"name": "", "body": "Steps:\n1. Go."}) != ""


def test_a_usable_draft_has_no_problem():
    assert SW.draft_problem(SW.parse_draft(GOOD)) == ""


def test_a_wrong_draft_is_still_shown():
    """Deliberately thinner than the rules for SAVING. A draft is allowed
    to be wrong, because the person reads it and edits it. What it may not
    be is empty, because then there is nothing to correct."""
    draft = SW.parse_draft(GOOD.replace(
        "description: Chase unpaid invoices. Use when an invoice is past its due date.",
        "description: x"))
    assert SW.draft_problem(draft) == ""
