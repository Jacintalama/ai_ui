"""A new agent picks the skills that fit what it is for (2026-11-10).

Lukas, 2026-11-10: "you already made the skills where it lists all the
available skills. So just assigning them to the new agent or having new
agents select which ones are relevant for him based on the description."

The main chat already suggested skills for a new agent, by keyword; the
agents page suggested none, leaving 68 to pick by hand. The keyword match was
weak. Measured against Jev on production the same day, six sample agents:

    "Keep our ClickUp tasks up to date, move tasks between columns, and
     remind people of deadlines."
        keyword  meeting-to-tasks
        Jev      daily-standup .85, task-from-conversation .83, day-ahead .78,
                 sprint-health .72
    "Research competitors and summarize market news into a short weekly
     report."
        keyword  research-and-cite, blocker-report, pricing-research
        Jev      competitor-scan .98, recurring-digest .96, brief-the-team .93

So Jev judges every skill against the description in one call (about 250 ms
there), and the keyword match is what happens when Jev cannot be asked.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_jev as j
import agent_skills
import routes_agents
from auth import CurrentUser, current_user

OWNER = "maker@example.com"
SKILLS = [("daily-standup", "Report what moved, what is stuck and what is due."),
          ("competitor-scan", "Find out what a competitor is doing now."),
          ("task-from-conversation", "Turn something said into a tracked task.")]


def _many(values: dict) -> dict:
    return {"model": "jev-1.13.0",
            "answers": {q: {"type": "noul", "noul": v} for q, v in values.items()},
            "usage": {"input_tokens": 900, "output_tokens": 80}}


@pytest.fixture
def seams(monkeypatch):
    calls = {"post": [], "record": []}
    state = {"reply": None, "error": None}

    async def post(body, key):
        calls["post"].append((body, key))
        if state["error"] is not None:
            raise state["error"]
        return state["reply"]

    async def record(row):
        calls["record"].append(row)

    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    monkeypatch.delenv("JEV_MODEL", raising=False)
    monkeypatch.delenv("JEV_DAILY_CALLS", raising=False)
    monkeypatch.setattr(j, "_post", post)
    monkeypatch.setattr(j, "record", record)
    monkeypatch.setattr(j, "_calls", {"day": "", "n": 0})
    return calls, state


# --- Jev's question --------------------------------------------------------------

async def test_one_yes_or_no_per_skill_in_one_call(seams):
    calls, state = seams
    state["reply"] = _many({"s0": 0.85, "s1": 0.2, "s2": 0.83})
    got = await j.pick_skills(OWNER, "Project manager. Keep our ClickUp tasks up to date.", SKILLS)
    assert len(calls["post"]) == 1
    body = calls["post"][0][0]
    assert set(body["questions"]) == {"s0", "s1", "s2"}
    assert all(q["type"] == "noul" for q in body["questions"].values())
    assert "daily-standup" in body["questions"]["s0"]["instructions"]
    assert "what is stuck" in body["questions"]["s0"]["instructions"]
    assert "Keep our ClickUp tasks up to date." in body["state"]
    assert got == ["daily-standup", "task-from-conversation"]


async def test_the_surest_comes_first(seams):
    _, state = seams
    state["reply"] = _many({"s0": 0.8, "s1": 0.98, "s2": 0.9})
    got = await j.pick_skills(OWNER, "x", SKILLS)
    assert got == ["competitor-scan", "task-from-conversation", "daily-standup"]


async def test_the_record_names_the_picks_and_not_the_description(seams):
    calls, state = seams
    state["reply"] = _many({"s0": 0.9, "s1": 0.1, "s2": 0.1})
    await j.pick_skills(OWNER, "my secret plan", SKILLS)
    row = calls["record"][0]
    assert row["purpose"] == j.PURPOSE_SKILLS
    assert row["outcome"] == "daily-standup"
    assert "secret" not in json.dumps(row, default=str)


async def test_nothing_sure_is_an_empty_list(seams):
    _, state = seams
    state["reply"] = _many({"s0": 0.3, "s1": 0.2, "s2": 0.1})
    assert await j.pick_skills(OWNER, "x", SKILLS) == []


async def test_jev_unavailable_is_none(seams, monkeypatch):
    calls, state = seams
    state["error"] = RuntimeError("down")
    assert await j.pick_skills(OWNER, "x", SKILLS) is None
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    assert await j.pick_skills(OWNER, "x", SKILLS) is None


async def test_no_description_or_no_skills_asks_nothing(seams):
    calls, _ = seams
    assert await j.pick_skills(OWNER, "   ", SKILLS) == []
    assert await j.pick_skills(OWNER, "x", []) == []
    assert calls["post"] == []


# --- pick_for: Jev, or the keywords -----------------------------------------------

POOL = {n: {"name": n, "description": d} for n, d in SKILLS}


async def test_pick_for_takes_jevs_picks(monkeypatch):
    async def jev(email, text, skills):
        assert {n for n, _d in skills} == set(POOL)
        return ["competitor-scan", "daily-standup"]
    monkeypatch.setattr(agent_skills, "_jev_pick", jev)
    assert await agent_skills.pick_for(OWNER, "research", POOL) == ["competitor-scan", "daily-standup"]


@pytest.mark.parametrize("jev_says", [None, []])
async def test_pick_for_falls_back_to_keywords(monkeypatch, jev_says):
    async def jev(email, text, skills):
        return jev_says
    monkeypatch.setattr(agent_skills, "_jev_pick", jev)
    monkeypatch.setattr(agent_skills, "suggest", lambda text, limit=3, pool=None: ["daily-standup"])
    assert await agent_skills.pick_for(OWNER, "standup", POOL) == ["daily-standup"]


async def test_pick_for_drops_a_name_that_is_not_a_skill(monkeypatch):
    async def jev(email, text, skills):
        return ["nope", "daily-standup"]
    monkeypatch.setattr(agent_skills, "_jev_pick", jev)
    assert await agent_skills.pick_for(OWNER, "x", POOL) == ["daily-standup"]


# --- the agents page's route -------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    got = {"connected": set(), "picked": [], "texts": []}

    async def connected(email):
        return set(got["connected"])

    async def mine(email):
        return []

    async def pick_for(email, text, pool):
        got["texts"].append(text)
        return list(got["picked"])
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    monkeypatch.setattr(routes_agents.user_skills, "mine", mine)
    monkeypatch.setattr(routes_agents.agent_skills, "pick_for", pick_for)
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    return TestClient(app), got


def test_the_route_returns_what_fits_and_what_needs_an_app(client):
    c, got = client
    got["picked"] = ["competitor-scan", "daily-standup", "research-and-cite"]
    r = c.get("/api/tasks/agents/skills/for",
              params={"role": "Researcher", "instructions": "Watch competitors."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert got["texts"] == ["Researcher Watch competitors."]
    # daily-standup needs a tracker, and nothing is connected.
    assert body["skills"] == ["competitor-scan", "research-and-cite"]
    assert [n["app"] for n in body["needs_connect"]] == ["tracker"]
    assert body["said"] == "Suggested from the description"


def test_the_route_with_no_description_suggests_nothing(client):
    c, got = client
    body = c.get("/api/tasks/agents/skills/for").json()
    assert body == {"skills": [], "needs_connect": [], "said": ""}
    assert got["texts"] == []


# --- the main chat's agent creation uses it, and keeps what was shown -----------

def test_skills_for_uses_the_ranking_it_is_given():
    pool = agent_skills.load_all()
    kept, unknown, suggested, gaps = routes_agents._skills_for(
        None, "Researcher", "Watch competitors.", {"gmail"}, pool,
        ranked=["competitor-scan", "recurring-digest", "brief-the-team", "summarise-a-link"])
    assert kept == ["competitor-scan", "recurring-digest", "brief-the-team"]
    assert suggested is True and unknown == []


async def test_confirming_makes_the_skills_that_were_shown(monkeypatch):
    """Jev answers twice, once for the preview and once for the confirm, and
    an answer near the cut can differ. The person approved what they saw."""
    answers = [["competitor-scan", "recurring-digest"], ["brief-the-team"]]

    async def pick_for(email, text, pool):
        return answers.pop(0)

    async def connected(email):
        return set()

    async def mine(email):
        return []

    async def roster(email):
        return []

    made = {}

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

    user = CurrentUser(email=OWNER)
    first = await routes_agents.make_agent(routes_agents.MakeAgentIn(
        name="Scout", instructions="Watch competitors.", role="Researcher"), user)
    assert first["created"] is False
    assert first["skills"] == ["competitor-scan", "recurring-digest"]
    second = await routes_agents.make_agent(routes_agents.MakeAgentIn(
        name="Scout", instructions="Watch competitors.", role="Researcher",
        confirm=first["confirm"]), user)
    assert second.get("skills") == ["competitor-scan", "recurring-digest"], second


# --- the agents page ---------------------------------------------------------------

def _page():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "agents.html")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _js_fn(src, name):
    start = src.index("function " + name + "(")
    return src[start:src.index("\n    }\n", start)]


def test_the_page_asks_for_skills_when_the_instructions_box_is_left():
    src = _page()
    assert '"/api/tasks/agents/skills/for?role="' in src
    assert '.addEventListener("blur", function () { suggestSkills(false); });' in src


def test_only_a_new_agent_with_untouched_skills_is_suggested_for():
    body = _js_fn(_page(), "suggestSkills")
    assert body.index("if (editingId) return;") < body.index("getJson(")
    assert "if (skillsTouched && !force) return;" in body


def test_a_tick_by_hand_stops_the_suggestions():
    assert 'wrap.addEventListener("change", function () { skillsTouched = true; });' in _page()


def test_opening_the_form_starts_fresh():
    body = _js_fn(_page(), "openForm")
    assert "skillsTouched = false;" in body and 'skillsAskedFor = "";' in body


def test_the_page_says_where_the_ticks_came_from():
    src = _page()
    assert 'id="skills-suggested"' in src and 'id="skills-suggest-again"' in src
    assert "Suggested from the description: " in src
