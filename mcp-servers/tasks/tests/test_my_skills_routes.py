"""The routes behind a skill somebody writes for themselves.

Drafting and saving are deliberately separate calls. A model that writes
instructions which then go into every one of an agent's turns must not be
able to install them unseen, which is the same brake added after the chat
announced an agent that never existed.

So: draft saves nothing and is allowed to be wrong, save validates and is
not. These test the join between those two, because the pieces either side
of a join are where this project keeps finding its bugs.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_skills
import routes_agents
import user_skills
from auth import CurrentUser, current_user

OWNER = "maker@example.com"

DRAFT = """---
name: Chase Invoices
description: Chase unpaid invoices. Use when one is past due.
allowed-tools: [gmail]
---
Steps:
1. List overdue invoices.
2. Draft one reminder each."""


@pytest.fixture
def client(monkeypatch):
    state = {"answer": DRAFT, "saved": [], "deleted": [], "mine": [],
             "tools": {"tools": [{"id": "gmail", "label": "Gmail"}]},
             "too_many": False}

    async def draft(email, job, tools):
        state["job"] = job
        state["tools_seen"] = tools
        return state["answer"]

    async def tools_for_email(email):
        return state["tools"]

    async def save(email, name, description, tools, body):
        if state["too_many"]:
            raise user_skills.TooMany()
        row = {"id": "s1", "name": name, "description": description,
               "tools": list(tools), "body": body}
        state["saved"].append(row)
        return row

    async def mine(email):
        return state["mine"]

    async def delete(email, name):
        state["deleted"].append(name)
        return name == "chase-invoices"

    monkeypatch.setattr(routes_agents, "_draft_seam", draft)
    monkeypatch.setattr(routes_agents, "tools_for_email", tools_for_email)
    monkeypatch.setattr(user_skills, "save", save)
    monkeypatch.setattr(user_skills, "mine", mine)
    monkeypatch.setattr(user_skills, "delete", delete)

    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    return TestClient(app), state


# --- drafting --------------------------------------------------------------

def test_a_draft_is_written_and_nothing_is_saved(client):
    c, state = client
    r = c.post("/api/tasks/agents/skills/draft", json={"job": "chase unpaid invoices"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "chase-invoices"
    assert body["tools"] == ["gmail"]
    assert body["body"].startswith("Steps:")
    assert state["saved"] == [], "a draft saved something"


def test_the_name_is_tidied_the_way_a_saved_one_would_be(client):
    """The model wrote "Chase Invoices". Showing that and then refusing it
    on save would be the page arguing with itself."""
    c, _ = client
    assert c.post("/api/tasks/agents/skills/draft",
                  json={"job": "x"}).json()["name"] == "chase-invoices"


def test_the_draft_is_told_which_tools_this_person_has(client):
    c, state = client
    c.post("/api/tasks/agents/skills/draft", json={"job": "chase invoices"})
    assert state["tools_seen"] == {"gmail": "Gmail"}


def test_a_draft_naming_an_unconnected_tool_warns(client):
    """It still returns the draft. People connect things later."""
    c, state = client
    state["tools"] = {"tools": [{"id": "calendar", "label": "Calendar"}]}
    body = c.post("/api/tasks/agents/skills/draft", json={"job": "x"}).json()
    assert "gmail" in body["warning"]
    assert body["body"].startswith("Steps:")


def test_an_empty_draft_says_what_to_do_instead_of_500ing(client):
    c, state = client
    state["answer"] = "   "
    r = c.post("/api/tasks/agents/skills/draft", json={"job": "x"})
    assert r.status_code == 422
    assert "sentence" in r.json()["detail"]


def test_tools_that_cannot_be_read_do_not_stop_the_draft(client, monkeypatch):
    """A skill written without knowing their tools is worse than one written
    with, and far better than no skill at all."""
    c, _ = client

    async def boom(email):
        raise RuntimeError("no")

    monkeypatch.setattr(routes_agents, "tools_for_email", boom)
    assert c.post("/api/tasks/agents/skills/draft", json={"job": "x"}).status_code == 200


# --- saving ----------------------------------------------------------------

def test_a_skill_is_saved_under_a_tidied_name(client):
    c, state = client
    r = c.post("/api/tasks/agents/skills/mine",
               json={"name": "Chase Invoices", "description": "d",
                     "body": "Steps:\n1. Go.", "tools": ["gmail"]})
    assert r.status_code == 200, r.text
    assert state["saved"][0]["name"] == "chase-invoices"


def test_saving_is_where_the_rules_are_applied(client):
    """A draft is allowed to be wrong. A saved skill is not."""
    c, state = client
    for bad, says in (
            ({"name": "x", "description": "", "body": "Steps."}, "what the skill is for"),
            ({"name": "x", "description": "d", "body": "  "}, "needs instructions"),
            ({"name": "", "description": "d", "body": "Steps."}, "name"),
    ):
        r = c.post("/api/tasks/agents/skills/mine", json=bad)
        assert r.status_code == 422, bad
        assert says in r.json()["detail"], bad
    assert state["saved"] == []


def test_an_oversized_body_is_refused_with_the_reason(client):
    """Refused by us with a sentence about prompts, not by the schema with
    "string too long", which says nothing anybody can act on."""
    c, _ = client
    r = c.post("/api/tasks/agents/skills/mine",
               json={"name": "x-y", "description": "d",
                     "body": "b" * (agent_skills.MAX_SKILL_CHARS + 1)})
    assert r.status_code == 422
    assert "every single message" in r.json()["detail"]


def test_the_limit_is_a_sentence_not_a_stack_trace(client):
    c, state = client
    state["too_many"] = True
    r = c.post("/api/tasks/agents/skills/mine",
               json={"name": "x-y", "description": "d", "body": "Steps."})
    assert r.status_code == 409
    assert str(user_skills.MAX_PER_PERSON) in r.json()["detail"]


def test_saving_warns_about_a_tool_that_is_not_connected(client):
    c, state = client
    state["tools"] = {"tools": []}
    body = c.post("/api/tasks/agents/skills/mine",
                  json={"name": "x-y", "description": "d",
                        "body": "Steps.", "tools": ["gmail"]}).json()
    assert "gmail" in body["warning"]


# --- listing and removing --------------------------------------------------

def test_my_skills_come_back_with_their_instructions(client):
    """Unlike /skills, which is everybody's and withholds bodies. This list
    is small, is only ever mine, and is shown on the page I edit them in."""
    c, state = client
    state["mine"] = [{"id": "s1", "name": "x-y", "description": "d",
                      "tools": [], "body": "Steps."}]
    body = c.get("/api/tasks/agents/skills/mine").json()
    assert body["skills"][0]["body"] == "Steps."


def test_one_can_be_removed(client):
    c, state = client
    assert c.delete("/api/tasks/agents/skills/mine/Chase Invoices").status_code == 200
    assert state["deleted"] == ["chase-invoices"]


def test_removing_one_that_is_not_mine_is_a_404(client):
    c, _ = client
    assert c.delete("/api/tasks/agents/skills/mine/not-mine").status_code == 404


def test_the_shipped_catalogue_is_untouched(client):
    """68 skills ship with the image and none of this changes that. The
    route everybody shares must not have become per-person."""
    c, _ = client
    r = c.get("/api/tasks/agents/skills")
    assert r.status_code == 200
    assert len(r.json()["skills"]) == len(agent_skills.load_all())


# --- saving exactly what was shown (2026-11-04) ---------------------------
# write_skill shows a draft and saves nothing; save_skill saves it. The
# draft is HELD on this side rather than re-sent, because a model asked to
# repeat 4000 characters paraphrases them, and then the person approves one
# text while another is stored. That is the failure a preview exists to
# prevent, reintroduced by the mechanism meant to prevent it.

def test_a_draft_hands_back_a_code(client):
    c, _ = client
    assert c.post("/api/tasks/agents/skills/draft",
                  json={"job": "chase invoices"}).json()["confirm"]


def test_the_code_saves_the_draft_exactly_as_shown(client):
    c, state = client
    draft = c.post("/api/tasks/agents/skills/draft",
                   json={"job": "chase invoices"}).json()
    r = c.post("/api/tasks/agents/skills/mine",
               json={"confirm": draft["confirm"]})
    assert r.status_code == 200, r.text
    saved = state["saved"][0]
    assert saved["name"] == draft["name"]
    assert saved["body"] == draft["body"]
    assert saved["tools"] == draft["tools"]


def test_a_code_cannot_be_spent_twice(client):
    """Otherwise an old transcript saves the same skill again, quietly."""
    c, state = client
    code = c.post("/api/tasks/agents/skills/draft",
                  json={"job": "x"}).json()["confirm"]
    assert c.post("/api/tasks/agents/skills/mine",
                  json={"confirm": code}).status_code == 200
    again = c.post("/api/tasks/agents/skills/mine", json={"confirm": code})
    assert again.status_code == 422
    assert "expired" in again.json()["detail"]
    assert len(state["saved"]) == 1


def test_a_code_nobody_issued_saves_nothing(client):
    c, state = client
    r = c.post("/api/tasks/agents/skills/mine", json={"confirm": "deadbeef1234"})
    assert r.status_code == 422
    assert state["saved"] == []


def test_a_code_belonging_to_somebody_else_saves_nothing(client, monkeypatch):
    """Keyed by code and checked against the email, so a code seen in
    another person's transcript cannot write into their account."""
    c, state = client
    code = c.post("/api/tasks/agents/skills/draft",
                  json={"job": "x"}).json()["confirm"]
    from auth import CurrentUser, current_user
    c.app.dependency_overrides[current_user] = lambda: CurrentUser(
        email="someone-else@example.com")
    r = c.post("/api/tasks/agents/skills/mine", json={"confirm": code})
    assert r.status_code == 422
    assert state["saved"] == []


def test_the_fields_are_ignored_when_a_code_is_given(client):
    """The whole point. A model that re-sends a shortened body must not be
    able to store it under a code the person approved."""
    c, state = client
    draft = c.post("/api/tasks/agents/skills/draft",
                   json={"job": "x"}).json()
    c.post("/api/tasks/agents/skills/mine",
           json={"confirm": draft["confirm"], "name": "something-else",
                 "description": "not what was shown", "body": "shorter"})
    saved = state["saved"][0]
    assert saved["name"] == draft["name"]
    assert saved["body"] == draft["body"]


def test_saving_without_a_code_still_works(client):
    """The form on the page sends fields, not a code. Both doors stay
    open."""
    c, state = client
    r = c.post("/api/tasks/agents/skills/mine",
               json={"name": "typed-by-hand", "description": "d",
                     "body": "Steps:\n1. Go."})
    assert r.status_code == 200
    assert state["saved"][0]["name"] == "typed-by-hand"
