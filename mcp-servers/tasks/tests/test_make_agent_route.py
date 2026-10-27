"""An agent made for the person by a model in the chat (2026-10-22).

The route, with Open WebUI replaced by a record of what it was asked.
"""
import importlib.util
import pathlib

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes_agents
from auth import CurrentUser, current_user

OWNER = "maker@example.com"


@pytest.fixture
def owui(monkeypatch):
    got = {"created": [], "roster": [{"id": "agent-mia-1", "name": "Mia", "role": "Receptionist"}]}

    async def roster_for(email):
        return list(got["roster"])

    async def user_id_for(email):
        return "u-1"

    async def create_model(token, body):
        got["created"].append(body)
        if body["id"].startswith("agent-dup"):
            return 401, {"detail": "Uh-oh! This model id is already registered."}
        return 200, {"id": body["id"]}

    monkeypatch.setattr(routes_agents, "_roster_for", roster_for)
    monkeypatch.setattr(routes_agents, "_owui_user_id_for", user_id_for)
    monkeypatch.setattr(routes_agents, "_create_model", create_model)
    monkeypatch.setattr(routes_agents, "mint_owui_token", lambda *a, **k: "tok")

    async def stamp(user_id):
        return "stamp"
    monkeypatch.setattr(routes_agents, "session_stamp_for", stamp)
    monkeypatch.setattr(routes_agents, "_default_model", lambda: "gpt-5")
    return got


@pytest.fixture
def client(owui):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    return TestClient(app)


def test_an_agent_is_made_with_the_agents_pages_own_body(client, owui):
    r = client.post("/api/tasks/agents/make", json={
        "name": "Jack", "role": "Bookkeeper", "instructions": "Keep the books straight.", "access": "ask"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Jack" and r.json()["id"].startswith("agent-jack-")
    body = owui["created"][0]
    # The IO pipe as the base, so @Jack in the main chat runs our loop,
    # and the platform default as the language model (agent_llm).
    assert body["base_model_id"] == "io.io"
    meta = dict(body["meta"])
    # The office robot as the profile picture (agent_avatar), by name.
    assert meta.pop("profile_image_url").startswith("data:image/svg+xml;base64,")
    assert meta == {"description": "Keep the books straight.", "toolIds": ["server:mcp-proxy"],
                    "agent_instructions": "Keep the books straight.", "access": "ask",
                    "role": "Bookkeeper", "llm": "gpt-5"}
    assert body["params"] == {"system": "Keep the books straight."}
    assert body["access_grants"] == [] and body["is_active"] is True


def test_the_rules_are_the_pages_rules(client, owui):
    bad = [
        ({"name": "Research Agent", "instructions": "x"}, "one word"),
        ({"name": "Jack", "instructions": ""}, "what to do"),
        ({"name": "Jack", "instructions": "x", "access": "root"}, "read, ask or all"),
        ({"name": "mia", "instructions": "x"}, "already have"),
    ]
    for body, said in bad:
        r = client.post("/api/tasks/agents/make", json=body)
        assert r.status_code == 400 and said in r.json()["detail"], (body, r.text)
    assert owui["created"] == []


def test_the_roster_lists_what_the_chat_needs(client):
    r = client.get("/api/tasks/agents/roster")
    assert r.status_code == 200
    assert r.json() == {"agents": [{"id": "agent-mia-1", "name": "Mia", "role": "Receptionist"}]}


def _tool():
    path = pathlib.Path(__file__).resolve().parents[3] / "open-webui-functions" / "agent_builder_tool.py"
    spec = importlib.util.spec_from_file_location("agent_builder_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Tools()


async def test_the_chat_tool_makes_an_agent_as_the_person_asking():
    tool = _tool()
    calls = []

    async def call(method, path, email, json_body=None):
        calls.append((method, path, email, json_body))
        if path == "/agents/make":
            return True, {"id": "agent-jack-1", "name": "Jack", "role": "Bookkeeper", "access": "ask"}
        return True, {"agents": [{"id": "agent-mia-1", "name": "Mia", "role": "Receptionist"}]}
    tool._call = call
    said = await tool.create_agent("Jack", "Keep the books.", role="Bookkeeper", access="ask",
                                   __user__={"email": "r@example.com"})
    assert said.startswith("Made Jack (Bookkeeper), with access, asking first.")
    assert calls[0] == ("POST", "/agents/make", "r@example.com",
                        {"name": "Jack", "instructions": "Keep the books.", "role": "Bookkeeper", "access": "ask"})
    said = await tool.list_my_agents(__user__={"email": "r@example.com"})
    assert said == "Your agents: Mia (Receptionist)."
    assert await tool.create_agent("Jack", "x", __user__={}) == "I do not know who is asking, so I cannot make an agent."



# --- bringing older agents up to date (2026-10-27) --------------------------

def _wire_refresh(monkeypatch, rows):
    import routes_agent_chat
    import routes_agents
    updated = []

    async def agents_for(email):
        return rows

    async def update(token, model_id, body):
        updated.append((model_id, body))
        return 200, {}

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agents, "_update_model", update)
    monkeypatch.setattr(routes_agents, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(routes_agents, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(routes_agents, "session_stamp_for", AsyncMock(return_value="s"))
    monkeypatch.setattr(routes_agents, "_default_model", lambda: "gpt-5")
    return updated


async def test_the_backfill_gives_a_face_and_moves_the_model_into_meta(monkeypatch):
    import routes_agents
    rows = [
        {"id": "agent-a", "name": "Ada", "base_model_id": "gpt-5", "meta": {"toolIds": ["gmail"]},
         "params": {"system": "Be Ada."}, "access_grants": [], "is_active": True},
        # Up to date already: on the pipe, with a model and a face.
        {"id": "agent-m", "name": "Mia", "base_model_id": "io.io",
         "meta": {"toolIds": [], "llm": "gpt-5", "profile_image_url": "data:image/png;base64,xx"},
         "params": {}, "access_grants": [], "is_active": True},
    ]
    updated = _wire_refresh(monkeypatch, rows)
    out = await routes_agents.refresh_agents(OWNER)
    assert out == {"updated": 1, "failed": 0}
    assert [m for m, _ in updated] == ["agent-a"]
    body = updated[0][1]
    assert body["base_model_id"] == "io.io"
    assert body["meta"]["llm"] == "gpt-5", "the model the owner chose was lost"
    assert body["meta"]["profile_image_url"].startswith("data:image/svg+xml;base64,")
    assert body["meta"]["toolIds"] == ["gmail"] and body["params"] == {"system": "Be Ada."}
    assert body["access_grants"] == []


async def test_an_agent_stuck_on_a_pipe_with_no_model_is_given_the_default(monkeypatch):
    import routes_agents
    rows = [{"id": "agent-s", "name": "Sam", "base_model_id": "auto_router.auto",
             "meta": {"profile_image_url": "data:image/png;base64,xx"},
             "params": {}, "access_grants": [], "is_active": True}]
    updated = _wire_refresh(monkeypatch, rows)
    assert await routes_agents.refresh_agents(OWNER) == {"updated": 1, "failed": 0}
    body = updated[0][1]
    assert body["base_model_id"] == "auto_router.auto" and body["meta"]["llm"] == "gpt-5"


async def test_a_failed_update_is_counted_and_the_rest_still_done(monkeypatch):
    import routes_agents
    rows = [
        {"id": "agent-a", "name": "Ada", "base_model_id": "gpt-5", "meta": {},
         "params": {}, "access_grants": [], "is_active": True},
        {"id": "agent-b", "name": "Bo", "base_model_id": "gpt-5", "meta": {},
         "params": {}, "access_grants": [], "is_active": True},
    ]
    _wire_refresh(monkeypatch, rows)

    async def flaky(token, model_id, body):
        if model_id == "agent-a":
            raise RuntimeError("down")
        return 200, {}
    monkeypatch.setattr(routes_agents, "_update_model", flaky)
    assert await routes_agents.refresh_agents(OWNER) == {"updated": 1, "failed": 1}
