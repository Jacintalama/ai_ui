"""The main chat's "which skills should I use?" and the Agents page's
"what does this agent's skill need?" (2026-11-04)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes_agents
from auth import CurrentUser, current_user

OWNER = "asker@example.com"


@pytest.fixture
def state(monkeypatch):
    got = {"connected": {"gmail"}, "mine": [], "asked": []}

    async def connected(email):
        got["asked"].append(email)
        return set(got["connected"])

    async def mine(email):
        return list(got["mine"])
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    monkeypatch.setattr(routes_agents.user_skills, "mine", mine)
    return got


@pytest.fixture
def client(state):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    return TestClient(app)


def test_suggest_reads_the_signed_in_persons_connections(client, state):
    r = client.get("/api/tasks/agents/skills/suggest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert state["asked"] == [OWNER]
    gmail = [g for g in body["ready"] if g["app"] == "gmail"][0]
    assert "inbox-triage" in gmail["skills"]
    assert "Gmail: " in body["message"]
    assert "[Connect Google Calendar](#aiui-connect:calendar)" in body["message"]
    assert all(c["app"] != "gmail" for c in body["connect"])


def test_suggest_names_the_persons_own_skills(client, state):
    state["mine"] = [{"name": "invoice-chaser", "description": "Chase invoices.",
                      "tools": [], "body": "x"}]
    body = client.get("/api/tasks/agents/skills/suggest").json()
    assert body["mine"] == ["invoice-chaser"]
    assert "Your own skills: invoice-chaser" in body["message"]


def test_needs_says_which_of_an_agents_skills_wait_on_an_app(client, state):
    state["connected"] = set()
    r = client.get("/api/tasks/agents/skills/needs",
                   params={"skills": "inbox-triage,shorten-this,daily-standup,nope"})
    assert r.status_code == 200, r.text
    assert r.json()["needs"] == [
        {"app": "gmail", "label": "Gmail", "skills": ["inbox-triage"],
         "connect": "#aiui-connect:gmail", "button": "Connect Gmail"},
        {"app": "tracker",
         "label": "a task tracker (Trello, GitHub, ClickUp or Jira)",
         "skills": ["daily-standup"], "connect": "#aiui-connect:trello",
         "button": "Connect a task tracker"}]


def test_needs_with_everything_connected_is_empty(client, state):
    state["connected"] = {"gmail", "trello"}
    r = client.get("/api/tasks/agents/skills/needs",
                   params={"skills": "inbox-triage,daily-standup"})
    assert r.json() == {"needs": []}
    assert client.get("/api/tasks/agents/skills/needs").json() == {"needs": []}


# --- the main chat's Skills tool ---------------------------------------------

def _skills_tool():
    import importlib.util
    import pathlib
    path = pathlib.Path(__file__).resolve().parents[3] / "open-webui-functions" / "skills_tool.py"
    spec = importlib.util.spec_from_file_location("skills_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Tools()


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


async def test_the_tool_asks_as_the_person_and_returns_the_message_whole():
    tool = _skills_tool()
    calls = []

    async def get(path, params, email):
        calls.append((path, params, email))
        return _Resp(200, {"message": "Gmail: inbox-triage\n[Connect Google Calendar](#aiui-connect:calendar)"})
    tool._get = get
    said = await tool.suggest_skills(__user__={"email": "r@example.com"})
    assert calls == [("/agents/skills/suggest", {}, "r@example.com")]
    # Whole, so the Connect link reaches the page and becomes a button.
    assert "[Connect Google Calendar](#aiui-connect:calendar)" in said


async def test_the_tool_says_plainly_when_it_cannot_ask():
    tool = _skills_tool()

    async def down(path, params, email):
        raise RuntimeError("refused")
    tool._get = down
    said = await tool.suggest_skills(__user__={"email": "r@example.com"})
    assert said == "Could not read your skills just now."
    assert await tool.suggest_skills(__user__={}) == (
        "I do not know who is asking, so I cannot suggest skills.")


def test_jev_picks_the_skills_tool_for_skills_that_fit_connections():
    import agent_jev
    """Measured live 2026-11-04: a note that only described the tool was
    not picked for these; naming the questions was (agent_jev comment)."""
    note = agent_jev.TOOL_NOTES["skills"].lower()
    for asked in ("suggest or recommend skills", "which skills they should use",
                  "fit the apps they have connected", "whether there is a skill"):
        assert asked in note, asked
