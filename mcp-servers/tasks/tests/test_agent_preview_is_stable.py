"""Making an agent from the main chat: saying yes must make it (2026-11-27).

Live, a person asked for an agent, saw the preview, said yes, and got a
SECOND preview with different skills, then a loop of previews and nothing
made. The model rarely copies the confirm code into its reply, so on "yes"
it asks for the preview again and confirms with the code that comes back.
That only works when the repeat preview of the same brief is the same
proposal. Each preview asked Jev for skills afresh, and an answer near the
cut changed between the two (none, then two skills), so the brief changed,
the code changed, and the person had to be asked again.
"""
import pytest

import routes_agents
from auth import CurrentUser

OWNER = "owner@example.com"


@pytest.fixture
def seams(monkeypatch):
    answers = [[], ["morning-briefing", "recurring-digest"], ["day-ahead"]]
    made = {}

    async def pick_for(email, text, pool):
        return answers.pop(0) if answers else ["other"]

    async def connected(email):
        return {"calendar"}

    async def mine(email):
        return []

    async def roster(email):
        return []

    async def create(token, body):
        made["body"] = body
        return 200, {}

    async def owui_id(email):
        return "u1"

    async def stamp(uid):
        return ""
    monkeypatch.setattr(routes_agents.agent_skills, "pick_for", pick_for)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    monkeypatch.setattr(routes_agents.user_skills, "mine", mine)
    monkeypatch.setattr(routes_agents, "_roster_for", roster)
    monkeypatch.setattr(routes_agents, "_create_model", create)
    monkeypatch.setattr(routes_agents, "_owui_user_id_for", owui_id)
    monkeypatch.setattr(routes_agents, "session_stamp_for", stamp)
    monkeypatch.setattr(routes_agents, "mint_owui_token", lambda *a, **k: "t")
    monkeypatch.setattr(routes_agents, "_PROPOSALS", {})
    monkeypatch.setattr(routes_agents, "_PROPOSAL_SKILLS", {})
    monkeypatch.setattr(routes_agents, "_BRIEF_SKILLS", {})
    return made


def _ask(**extra):
    return routes_agents.MakeAgentIn(
        name="Wren", instructions="Read my calendar each morning.",
        role="Calendar brief writer", **extra)


async def test_the_same_brief_previewed_twice_is_the_same_proposal(seams):
    user = CurrentUser(email=OWNER)
    first = await routes_agents.make_agent(_ask(), user)
    again = await routes_agents.make_agent(_ask(), user)
    assert first["created"] is False and again["created"] is False
    assert again["skills"] == first["skills"]
    assert again["confirm"] == first["confirm"]


async def test_yes_after_a_repeat_preview_makes_the_agent(seams):
    user = CurrentUser(email=OWNER)
    await routes_agents.make_agent(_ask(), user)
    again = await routes_agents.make_agent(_ask(), user)
    done = await routes_agents.make_agent(_ask(confirm=again["confirm"]), user)
    assert done.get("id", "").startswith("agent-wren-"), done
    assert "body" in seams


async def test_a_changed_brief_is_asked_again(seams):
    """Changing the wording is still a new proposal: the person approved a
    brief, not a name."""
    user = CurrentUser(email=OWNER)
    first = await routes_agents.make_agent(_ask(), user)
    other = await routes_agents.make_agent(routes_agents.MakeAgentIn(
        name="Wren", instructions="Read my calendar each EVENING.",
        role="Calendar brief writer"), user)
    assert other["confirm"] != first["confirm"]


async def test_skills_the_person_names_still_win(seams):
    user = CurrentUser(email=OWNER)
    await routes_agents.make_agent(_ask(), user)
    named = await routes_agents.make_agent(_ask(skills=["day-ahead"]), user)
    assert named["skills"] == ["day-ahead"]


async def test_a_made_agent_forgets_its_brief(seams):
    user = CurrentUser(email=OWNER)
    first = await routes_agents.make_agent(_ask(), user)
    await routes_agents.make_agent(_ask(confirm=first["confirm"]), user)
    assert routes_agents._BRIEF_SKILLS == {}


async def test_an_app_connected_between_previews_still_counts(seams, monkeypatch):
    """The ranking is kept, not the result: connect Gmail after the first
    preview and the repeat offers the Gmail skill it held back."""
    have = set()

    async def connected(email):
        return set(have)

    async def pick_for(email, text, pool):
        return ["inbox-triage", "recurring-digest"]
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    monkeypatch.setattr(routes_agents.agent_skills, "pick_for", pick_for)
    user = CurrentUser(email=OWNER)
    first = await routes_agents.make_agent(_ask(), user)
    assert "inbox-triage" not in first["skills"]
    have.add("gmail")
    again = await routes_agents.make_agent(_ask(), user)
    assert again["skills"][0] == "inbox-triage"
