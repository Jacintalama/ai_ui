"""Skills somebody wrote for themselves.

The platform ships 68 skills and, until now, there was no way to make a
sixty-ninth. A skill is a folder in the image, so somebody whose job the 68
do not cover needed a pull request and a deploy.

Designed on 2026-09-09 in
docs/superpowers/specs/2026-09-09-agent-skill-writer-design.md and unbuilt
for eight weeks. Importing skills instead was measured and rejected there:
of 1,225 public SKILL.md files, 2.9% were usable, because public skills are
written for an agent that reads files on demand and these are pasted whole
into a small model's prompt.

What these pin down is the part that is dangerous rather than the part that
is new. A saved skill is injected into every turn of every agent holding
it, so the rules about size, about names, and about what a missing tool
does are not tidiness.
"""
import pytest

import agent_skills
import user_skills as US

BODY = "Steps:\n1. Read the invoice.\n2. Say what is late."


# --- the name --------------------------------------------------------------

def test_a_name_somebody_typed_becomes_a_name_we_store():
    """"Chase Invoices" is obviously chase-invoices. Bouncing it teaches
    nobody anything."""
    assert US.clean_name("Chase Invoices") == "chase-invoices"
    assert US.clean_name("  inbox   triage  ") == "inbox-triage"
    assert US.clean_name("Daily_Standup") == "daily-standup"


def test_a_name_is_the_shape_the_built_in_ones_are():
    """So a person's skill and a shipped one are the same kind of thing
    with the same kind of id."""
    assert US.problem_with("chase-invoices", "d", BODY, 4000) == ""
    for bad in ("Chase Invoices", "chase--invoices", "-chase", "chase-",
                "chase_invoices", "chase invoices", ""):
        assert US.problem_with(bad, "d", BODY, 4000) != "", bad


def test_a_name_is_bounded():
    long_name = "a" * (US.MAX_NAME_CHARS + 10)
    assert US.problem_with(long_name, "d", BODY, 4000) != ""


# --- the description -------------------------------------------------------

def test_a_skill_has_to_say_what_it_is_for():
    """That line is the whole basis on which anybody picks it, and on which
    suggest() scores it."""
    problem = US.problem_with("chase-invoices", "   ", BODY, 4000)
    assert "what the skill is for" in problem
    assert "when to use it" in problem


def test_a_description_is_bounded():
    assert US.problem_with("x-y", "d" * (US.MAX_DESCRIPTION_CHARS + 1),
                           BODY, 4000) != ""


# --- the body, which is the expensive one ----------------------------------

def test_a_skill_needs_instructions():
    assert US.problem_with("chase-invoices", "d", "   ", 4000) != ""


def test_the_body_is_capped_and_the_reason_is_given():
    """A skill's whole body goes into the prompt on every message. Somebody
    told only "too long" will trim it to the number and wonder why; told
    why, they write a shorter skill."""
    problem = US.problem_with("x-y", "d", "b" * 4001, 4000)
    assert "4001" in problem and "4000" in problem
    assert "every single message" in problem


def test_the_cap_comes_from_the_caller():
    """agent_skills owns the number the prompt actually enforces. A second
    copy here would be free to drift from the one that is real."""
    assert US.problem_with("x-y", "d", "b" * 500, 400) != ""
    assert US.problem_with("x-y", "d", "b" * 500, 4000) == ""


def test_the_cap_the_caller_should_pass_is_the_real_one():
    """Not asserted by the function, so asserted here: the number to hand
    it is the one agent_skills enforces when it builds a brief."""
    assert agent_skills.MAX_SKILL_CHARS == 4000
    assert US.problem_with("x-y", "d", "b" * (agent_skills.MAX_SKILL_CHARS + 1),
                           agent_skills.MAX_SKILL_CHARS) != ""


# --- a tool that is not connected ------------------------------------------

def test_an_unconnected_tool_is_a_warning_and_never_a_refusal():
    """People connect things later. A refusal would be wrong the moment
    they did, and a silent save is the failure worth warning about."""
    warning = US.tool_warning(["gmail"], {"calendar": "Calendar"})
    assert "gmail" in warning
    assert "still save" in warning


def test_several_missing_tools_read_as_a_list():
    warning = US.tool_warning(["gmail", "trello"], {})
    assert "gmail" in warning and "trello" in warning


def test_a_skill_whose_tools_are_all_connected_says_nothing():
    assert US.tool_warning(["gmail"], {"gmail": "Gmail"}) == ""
    assert US.tool_warning([], {}) == ""
    assert US.tool_warning(None, {}) == ""


# --- a person's own skill wins over a built-in -----------------------------

def test_my_own_skill_beats_a_built_in_of_the_same_name():
    """The alternative is a deploy that adds a built-in quietly replacing
    something somebody wrote, which is the worse failure."""
    built_in = {"inbox-triage": {"name": "inbox-triage",
                                 "description": "the shipped one",
                                 "tools": [], "tags": []}}
    merged = US.merge(built_in, [{"name": "inbox-triage",
                                  "description": "mine", "tools": [],
                                  "body": BODY}])
    assert merged["inbox-triage"]["description"] == "mine"
    assert merged["inbox-triage"]["mine"] is True


def test_the_built_in_ones_are_all_still_there():
    built_in = {"a-skill": {"name": "a-skill", "description": "x",
                            "tools": [], "tags": []}}
    merged = US.merge(built_in, [{"name": "b-skill", "description": "y",
                                  "tools": [], "body": BODY}])
    assert set(merged) == {"a-skill", "b-skill"}
    assert "mine" not in merged["a-skill"]


def test_a_persons_skill_looks_like_a_built_in_one():
    """So everything downstream treats them identically. brief_for and
    selected() must not need to know which kind they have."""
    skill = US.as_skill({"name": "x-y", "description": "d",
                         "tools": ["gmail"], "body": BODY})
    built_in = next(iter(agent_skills.load_all().values()), None)
    if built_in:
        for field in ("name", "description", "tools", "tags"):
            assert field in skill and field in built_in


def test_merging_nothing_changes_nothing():
    built_in = {"a-skill": {"name": "a-skill"}}
    assert US.merge(built_in, []) == built_in
    assert US.merge(built_in, None) == built_in


def test_a_nameless_row_cannot_shadow_anything():
    built_in = {"a-skill": {"name": "a-skill"}}
    assert US.merge(built_in, [{"name": "", "description": "d"}]) == built_in


# --- reading them never costs somebody their turn --------------------------

async def test_a_database_that_cannot_be_read_costs_the_skills_not_the_turn(
        monkeypatch):
    """The rule this codebase already follows: bookkeeping must never cost
    somebody their turn. Without their own skills they are where this
    platform was yesterday, which is working."""
    async def boom(email):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(US, "_rows_seam", boom)
    assert await US.mine("ralph@example.com") == []


async def test_nobody_is_not_a_query(monkeypatch):
    """Most agents have no skills at all. A round trip for nothing is paid
    by every person on the platform for a feature few of them use."""
    called = []

    async def spy(email):
        called.append(email)
        return []

    monkeypatch.setattr(US, "_rows_seam", spy)
    assert await US.mine("") == []
    assert await US.mine(None) == []
    assert called == []


async def test_a_delete_that_fails_is_false_not_an_exception(monkeypatch):
    async def boom(email, name):
        raise RuntimeError("no")

    monkeypatch.setattr(US, "_delete_seam", boom)
    assert await US.delete("r@example.com", "x-y") is False


# --- how many ---------------------------------------------------------------

async def test_a_person_is_capped(monkeypatch):
    """Not a prompt limit, a picker limit. An agent holds about ten and
    brief_for enforces that; this stops the list itself becoming unusable."""
    async def full(email, name, description, tools, body):
        raise US.TooMany()

    monkeypatch.setattr(US, "_save_seam", full)
    with pytest.raises(US.TooMany):
        await US.save("r@example.com", "x-y", "d", [], BODY)


def test_the_cap_is_well_clear_of_what_one_agent_can_hold():
    """Ten skills is about 7,600 characters against a 8,000 budget, so the
    per-agent ceiling is ten. The library may be larger than that."""
    assert US.MAX_PER_PERSON > 10
    assert agent_skills.MAX_TOTAL_CHARS == 8000
