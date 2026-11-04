"""A skill you wrote can be ticked onto an agent.

Shipped on 2026-11-04: a person describes a job in the main chat and gets
a skill of their own. The chat wrote it, /skills/mine returned it, and
agent_skills.selected could follow it.

The agent form never fetched it. So the one place a skill is actually
USED could not see any skill its owner had written, and could not make
one either. Half a feature, found the same day by reading the comment
above the loader, which said there was "nothing per-user to refresh".

Structural, like the other tests of this page. What they pin down are the
decisions that would be quietly wrong.
"""
import os
import re

import pytest

PAGE = os.path.join(os.path.dirname(__file__), "..", "static", "agents.html")


def _page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def _fn(name):
    """One function's body, to the next function at the same indent."""
    src = _page()
    start = src.index("function " + name)
    nxt = src.find("\n    function ", start + 10)
    nxt2 = src.find("\n    async function ", start + 10)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return src[start:min(ends)] if ends else src[start:]


# --- the gap this closes ---------------------------------------------------

def test_the_form_asks_for_my_own_skills():
    body = _fn("loadSkills")
    assert "/api/tasks/agents/skills/mine" in body


def test_my_own_skills_failing_does_not_cost_me_the_library():
    """Sixty-four shipped skills are the main thing on this form. A
    per-user query that errors must not empty it."""
    body = _fn("loadSkills")
    assert ".catch(" in body
    assert "return null" in body


def test_both_are_fetched_at_once():
    """One is a file on the server and the other a query. Serialising them
    adds a round trip to opening a form."""
    assert "Promise.all" in _fn("loadSkills")


def test_mine_wins_on_a_name_clash():
    """user_skills.merge does exactly this on the server. One rule in two
    places is two answers eventually."""
    assert "byName[s.name] || s" in _fn("loadSkills")


def test_the_shipped_order_is_kept():
    """Sorting the merged list by name was the obvious thing and was
    wrong: the server hands these over in a deliberate order. A browser
    test caught it, which is why this one exists next to it."""
    body = _fn("loadSkills")
    assert ".sort()" not in body, (
        "the list is being reordered, discarding the server's order")
    assert "shipped.filter" in body


def test_my_own_skills_are_appended_rather_than_dropped():
    """A skill of mine whose name is in no shipped file must still appear,
    which is every skill anybody writes."""
    body = _fn("loadSkills")
    assert "SKILL_LIST.push(s)" in body
    # The NEGATED guard. `already[s.name] = true` appears just above, so a
    # presence check on the name passes while the guard is gone and a
    # clashing skill is listed twice.
    assert "!already[s.name]" in body, "it would be added twice on a clash"


def test_my_skills_are_marked_in_the_list():
    """Sixty-four rows, and one of them is yours. Without a mark there is
    no way to tell, and no way to search for it."""
    # The ASSIGNMENT in the drawing, not the name anywhere on the page.
    # MY_SKILLS[s.name] also appears where the map is filled, so a mere
    # presence check passes with `var mine = false` and no mark drawn.
    # That is the fifth presence-for-specific slip today; they are all
    # written up where they bit.
    assert "var mine = !!MY_SKILLS[s.name];" in _fn("drawSkills")
    assert "yours" in _page()


# --- writing one from here -------------------------------------------------

def test_the_draft_is_shown_before_anything_is_saved():
    """A skill is instructions an agent follows unattended. Nobody should
    get one they have not read."""
    src = _page()
    assert "newskill-draft" in src
    draft = _fn("newSkillDraft")
    assert "/api/tasks/agents/skills/draft" in draft
    assert "skills/mine" not in draft, (
        "the draft step must not save; that is the second step")


def test_saving_is_a_separate_step():
    save = _fn("newSkillSave")
    assert "/api/tasks/agents/skills/mine" in save
    assert '"POST"' in save


def test_the_real_reason_is_shown_when_it_is_refused():
    """Both routes raise HTTPException, so FastAPI reports the reason as
    `detail`. Reading only `problem` would swallow every useful one: the
    draft expired, or you are at your fifty."""
    for name in ("newSkillDraft", "newSkillSave"):
        body = _fn(name)
        assert "body.detail" in body, name


def test_the_new_skill_is_ticked_on_the_agent_being_edited():
    """Somebody who writes a skill while editing an agent wants it on that
    agent. Saving and leaving it unticked is a second thing to remember."""
    body = _fn("newSkillSave")
    assert "loadSkills()" in body
    assert "checked = true" in body


def test_a_warning_does_not_block_saving():
    """The writer says when a draft leans on an app this person has not
    connected. The skill is still fine; it just cannot do everything yet."""
    body = _fn("newSkillDraft")
    assert "warning" in body
    assert "return" not in body.split("body.warning")[1].split("}")[0]


# --- the trap in redrawing a list ------------------------------------------

def test_listeners_are_bound_once_not_once_per_draw():
    """The list is redrawn every time somebody writes a skill. Binding
    inside the draw adds a second copy of every listener each time, so the
    third skill you write opens three dialogs."""
    src = _page()
    assert "function bindSkillControls" in src
    # The GUARD, not the flag's name. Deleting the early return leaves the
    # name in place on the line below it and binds a second copy of every
    # listener per redraw, so the third skill you write opens three
    # dialogs.
    assert "if (skillControlsBound) return;" in src
    drawing = _fn("drawSkills")
    assert "addEventListener" not in drawing, (
        "a listener is still being bound inside the redraw")
