"""What the form is allowed to offer this person.

Today the form offers Gmail to all 9 users and only 1 of them has a Gmail
token, so 8 people can tick a box that silently does nothing.
"""
from unittest.mock import AsyncMock, patch

import routes_agents


async def test_a_tool_needing_no_connection_is_always_available():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["documents", "remember"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("nobody@example.com")

    by_id = {t["id"]: t for t in out["tools"]}
    assert by_id["documents"]["connected"] is True
    assert by_id["remember"]["connected"] is True


async def test_gmail_is_not_connected_without_a_token():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["gmail"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("nobody@example.com")

    gmail = out["tools"][0]
    assert gmail["connected"] is False
    assert gmail["connect_url"], "it offered no way to fix it"


async def test_gmail_is_connected_when_the_user_has_a_token():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["gmail"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value={"gmail"})):
        out = await routes_agents.tools_for_email("ralph@example.com")

    assert out["tools"][0]["connected"] is True


async def test_connection_state_is_read_for_the_asking_user():
    """One person's Gmail must never make it look connected for another."""
    probe = AsyncMock(return_value=set())
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["gmail"])), \
         patch.object(routes_agents, "_connected_providers", new=probe):
        await routes_agents.tools_for_email("asker@example.com")

    probe.assert_awaited_once_with("asker@example.com")


async def test_a_newly_installed_tool_appears_without_a_code_change():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["brand_new_tool"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("x@example.com")

    # Present, not necessarily alone: the connected apps umbrella is always
    # appended and is not a row in public.tool.
    ids = [t["id"] for t in out["tools"]]
    assert "brand_new_tool" in ids, ids
    assert out["tools"][0]["label"], "it had no label to show"


async def test_the_connected_apps_umbrella_follows_user_connections():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=[])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value={"clickup"})):
        out = await routes_agents.tools_for_email("x@example.com")

    umbrella = [t for t in out["tools"] if t["id"] == "server:mcp-proxy"]
    assert umbrella and umbrella[0]["connected"] is True


async def test_the_umbrella_is_offered_even_with_nothing_connected():
    """It used to appear only once a proxy app was connected, so on a platform
    where nobody has connected one it vanished from the form. The starter
    agent Scout uses this exact tool, and a form that never renders its
    checkbox saves the agent without it."""
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=[])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("nobody@example.com")

    umbrella = [t for t in out["tools"] if t["id"] == "server:mcp-proxy"]
    assert umbrella, "the connected apps tool was not offered at all"
    assert umbrella[0]["connected"] is False
    assert umbrella[0]["connect_url"], "it offered no way to connect one"


async def test_google_tokens_alone_do_not_light_up_the_umbrella():
    """Gmail is not a Connect Your Own App provider."""
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=[])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value={"gmail", "calendar", "gdrive"})):
        out = await routes_agents.tools_for_email("ralph@example.com")

    umbrella = [t for t in out["tools"] if t["id"] == "server:mcp-proxy"][0]
    assert umbrella["connected"] is False
