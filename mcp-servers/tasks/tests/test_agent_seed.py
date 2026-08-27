"""Seeding a user their own copies of the starter agents.

The assertions about WHO the agents are created for exist because a review on
this codebase twice found identity mutations that passed a full suite.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

import routes_agents


async def test_a_new_user_gets_a_copy_of_every_template():
    created = []

    async def fake_create(token, body):
        created.append(body)
        return 200, {"id": body["id"]}

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=fake_create):
        out = await routes_agents.seed_for_email("newbie@example.com")

    assert out["created"] == 2
    names = sorted(b["name"] for b in created)
    assert names == ["Scout", "Triage"]


async def test_the_copies_are_created_for_that_user_and_nobody_else():
    resolver = AsyncMock(return_value="uid-1")
    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=resolver), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=AsyncMock(return_value=(200, {}))):
        await routes_agents.seed_for_email("newbie@example.com")

    resolver.assert_awaited_once_with("newbie@example.com")


async def test_nothing_seeded_carries_a_grant():
    """A copy belongs to one person. Sharing is what we are getting rid of."""
    created = []

    async def fake_create(token, body):
        created.append(body)
        return 200, {}

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=fake_create):
        await routes_agents.seed_for_email("newbie@example.com")

    for body in created:
        assert body["access_grants"] == []


async def test_a_user_who_was_already_seeded_gets_nothing():
    create = AsyncMock()
    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=True)), \
         patch.object(routes_agents, "_create_model", new=create):
        out = await routes_agents.seed_for_email("old@example.com")

    create.assert_not_awaited(), "it seeded somebody twice"
    assert out == {"seeded": False, "created": 0}


async def test_the_seed_is_recorded_even_when_a_template_fails():
    """Otherwise a user whose first copy failed is nagged forever."""
    mark = AsyncMock()

    async def half_fails(token, body):
        return (200, {}) if body["name"] == "Scout" else (500, "boom")

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=mark), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=half_fails):
        out = await routes_agents.seed_for_email("half@example.com")

    mark.assert_awaited_once()
    assert out["created"] == 1


async def test_a_duplicate_id_is_retried_once_with_a_new_suffix():
    seen = []

    async def collide(token, body):
        seen.append(body["id"])
        if len(seen) == 1:
            return 401, {"detail": "Model id already registered"}
        return 200, {}

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=collide):
        await routes_agents.seed_for_email("dupe@example.com")

    assert len(seen) >= 2, "it gave up instead of retrying"
    assert seen[0] != seen[1], "it retried with the same id"


async def test_seeding_never_raises_to_the_caller():
    with patch.object(routes_agents, "_already_seeded",
                      new=AsyncMock(side_effect=RuntimeError("db down"))):
        out = await routes_agents.seed_for_email("x@example.com")
    assert out == {"seeded": False, "created": 0}


async def test_an_unknown_user_is_not_seeded():
    create = AsyncMock()
    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value=None)), \
         patch.object(routes_agents, "_create_model", new=create):
        out = await routes_agents.seed_for_email("ghost@example.com")
    create.assert_not_awaited()
    assert out["created"] == 0
