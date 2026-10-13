"""Every route that mints an Open WebUI token carries the user's session stamp.

Open WebUI 0.12.0's is_valid_token rejects a token whose session_stamp claim
differs from public.auth.session_stamp for that user. A route that forgot to
pass it would still work for every user that predates the upgrade (their
column is NULL) and 401 for everyone created after it, which is exactly the
kind of failure a test against old accounts never sees.

agent_runner.run_agent is covered in test_agent_runner.py, on its own fixture.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routes_agent_turn as rt
import routes_agents
import routes_gateway


class _Mint:
    """Stands in for mint_owui_token and records what each call carried."""

    def __init__(self):
        self.calls = []

    def __call__(self, user_id, ttl_seconds=60, session_stamp=None):
        self.calls.append({"user_id": user_id, "session_stamp": session_stamp})
        return "tok"


@pytest.fixture
def mint(monkeypatch):
    m = _Mint()
    for mod in (rt, routes_agents, routes_gateway):
        monkeypatch.setattr(mod, "mint_owui_token", m)
    return m


@pytest.fixture
def stamp_for(monkeypatch):
    s = AsyncMock(return_value="stamp-x")
    for mod in (rt, routes_agents, routes_gateway):
        monkeypatch.setattr(mod, "session_stamp_for", s, raising=False)
    return s


async def test_resolving_an_agent_row_carries_the_stamp(monkeypatch, mint, stamp_for):
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="uid-1"))
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    with pytest.raises(HTTPException):
        await rt._resolve_agent_row("a@example.com", "agent-x")
    assert mint.calls == [{"user_id": "uid-1", "session_stamp": "stamp-x"}]
    stamp_for.assert_awaited_once_with("uid-1")


async def test_listing_agents_for_routing_carries_the_stamp(monkeypatch, mint, stamp_for):
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="uid-1"))
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    assert await rt._agents_for("a@example.com") == []
    assert mint.calls == [{"user_id": "uid-1", "session_stamp": "stamp-x"}]
    stamp_for.assert_awaited_once_with("uid-1")


async def test_io_answering_for_itself_carries_the_stamp(monkeypatch, mint, stamp_for):
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="uid-1"))
    monkeypatch.setattr(rt, "_post_chat", AsyncMock(return_value={
        "choices": [{"message": {"content": "hi"}}]}))
    assert await rt._answer_as_io("a@example.com", []) == "hi"
    assert mint.calls == [{"user_id": "uid-1", "session_stamp": "stamp-x"}]
    stamp_for.assert_awaited_once_with("uid-1")


async def test_seeding_starter_agents_carries_the_stamp(monkeypatch, mint, stamp_for):
    monkeypatch.setattr(routes_agents, "_already_seeded", AsyncMock(return_value=False))
    monkeypatch.setattr(routes_agents, "_mark_seeded", AsyncMock())
    monkeypatch.setattr(routes_agents, "_owui_user_id_for",
                        AsyncMock(return_value="uid-1"))
    monkeypatch.setattr(routes_agents, "_create_model",
                        AsyncMock(return_value=(200, {})))
    out = await routes_agents.seed_for_email("newbie@example.com")
    assert out["seeded"] is True
    assert mint.calls == [{"user_id": "uid-1", "session_stamp": "stamp-x"}]
    stamp_for.assert_awaited_once_with("uid-1")


async def test_a_linked_gateway_user_gets_a_token_with_the_stamp(
        monkeypatch, mint, stamp_for):
    link = SimpleNamespace(email="a@example.com", owui_user_id="uid-1")

    class _S:
        async def execute(self, statement, params=None):
            return SimpleNamespace(scalar_one_or_none=lambda: link)

    @asynccontextmanager
    async def _session():
        yield _S()

    monkeypatch.setattr(routes_gateway, "session", _session)
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "s3cret")
    out = await routes_gateway.resolve(
        routes_gateway.ResolveIn(platform="discord", platform_user_id="42"),
        x_internal_secret="s3cret")
    assert out["linked"] is True and out["owui_token"] == "tok"
    assert mint.calls == [{"user_id": "uid-1", "session_stamp": "stamp-x"}]
    stamp_for.assert_awaited_once_with("uid-1")
