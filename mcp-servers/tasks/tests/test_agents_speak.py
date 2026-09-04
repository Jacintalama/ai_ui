"""The one door the page uses to make a further agent speak.

It opens onto _turn_for, which already has its own gate, so the only thing
this route adds is: prove who is asking, and let them run only their own
agents. A stranger's token, or no token, must reach nothing.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

import routes_agents
from auth import CurrentUser, current_user

ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
OWNER = "speak-owner@example.com"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    monkeypatch.setattr(routes_agents, "_agents_for",
                        AsyncMock(return_value=[ADA, MIA]))
    monkeypatch.setattr(routes_agents, "_turn_for",
                        AsyncMock(return_value={"answer": "hi from mia", "notes": ["a note"],
                                                "agent": {"id": "agent-m", "name": "Mia"}}))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


BODY = {"chat_id": "chat-1", "agent_id": "agent-m",
        "messages": [{"role": "user", "content": "hi team"},
                     {"role": "assistant", "content": "hello from ada"}]}


async def test_an_owner_can_make_their_own_agent_speak(client):
    r = await client.post("/api/tasks/agents/speak", json=BODY)
    assert r.status_code == 200
    assert r.json() == {"answer": "hi from mia", "notes": ["a note"],
                        "agent": {"id": "agent-m", "name": "Mia"}}


async def test_the_turn_runs_through_the_same_loop_as_every_other(client):
    """_turn_for is what applies the access level, cleans the labels out of
    history and records the run. This route must call it, not _run_turn."""
    await client.post("/api/tasks/agents/speak", json=BODY)
    routes_agents._turn_for.assert_awaited_once()
    args = routes_agents._turn_for.await_args.args
    assert args[0] == OWNER
    assert args[1] == MIA
    assert args[2] == BODY["messages"]
    assert sorted(args[3]) == ["Ada", "Mia"]


async def test_an_agent_the_caller_does_not_own_is_refused(client):
    r = await client.post("/api/tasks/agents/speak",
                          json={**BODY, "agent_id": "agent-somebody-elses"})
    assert r.status_code == 403
    routes_agents._turn_for.assert_not_awaited()


async def test_no_token_reaches_nothing(monkeypatch):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")

    def _refuse():
        raise HTTPException(status_code=401, detail="no")
    app.dependency_overrides[current_user] = _refuse
    monkeypatch.setattr(routes_agents, "_turn_for", AsyncMock())
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    r = await c.post("/api/tasks/agents/speak", json=BODY)
    assert r.status_code == 401
    routes_agents._turn_for.assert_not_awaited()


@pytest.mark.parametrize("bad", [
    {"chat_id": "c", "agent_id": "", "messages": []},
    {"chat_id": "", "agent_id": "agent-m", "messages": []},
    {"chat_id": "c", "agent_id": "agent-m"},
])
async def test_a_malformed_request_is_a_422_not_a_500(client, bad):
    r = await client.post("/api/tasks/agents/speak", json=bad)
    assert r.status_code == 422


async def test_an_oversized_history_is_refused_before_any_agent_runs(client):
    """The first browser-reachable path into a turn. The loop re-posts
    the whole conversation each iteration, so an unbounded history is
    an unbounded bill and an unbounded memory footprint."""
    too_many = {**BODY, "messages": [{"role": "user", "content": "x"}] * 201}
    r = await client.post("/api/tasks/agents/speak", json=too_many)
    assert r.status_code == 422
    too_long = {**BODY, "messages": [{"role": "user", "content": "x" * 32001}]}
    r = await client.post("/api/tasks/agents/speak", json=too_long)
    assert r.status_code == 422
    routes_agents._turn_for.assert_not_awaited()
    # And exactly at the bound is fine.
    at_bound = {**BODY, "messages": [{"role": "user", "content": "x" * 32000}] * 200}
    r = await client.post("/api/tasks/agents/speak", json=at_bound)
    assert r.status_code == 200
