"""The connection sweep re-lists a person's own MCP servers.

Three failed checks in a row and the card reads "Not answering since": the
tools stay listed, because a server down for an hour should not make agents
forget it exists. A server that answers again is good again.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connection_sweep as S  # noqa: E402
import own_mcp_client  # noqa: E402
import own_mcp_store  # noqa: E402

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=30)
FRESH = NOW - timedelta(hours=1)


def _row(sid, email="a@x.com", checked=OLD):
    return {"id": sid, "email": email, "slug": "acme", "label": "Acme",
            "host": "mcp.example.com", "tools": [{"name": "own-acme_t", "tool": "t"}],
            "check_ok": True, "fails": 0, "checked_at": checked}


@pytest.fixture
def world(monkeypatch):
    seen = {"set": [], "checks": [], "listed": []}
    rows = [_row("s1"), _row("s2", email="b@x.com"), _row("s3", checked=FRESH)]
    monkeypatch.setattr(own_mcp_store, "all_rows", AsyncMock(return_value=rows))
    monkeypatch.setattr(own_mcp_store, "secrets_of", AsyncMock(
        return_value={"url": "https://mcp.example.com/mcp", "token": "t"}))

    async def set_tools(email, sid, tools):
        seen["set"].append((email, sid, [t["tool"] for t in tools]))
        return True

    async def record(email, sid, ok):
        seen["checks"].append((email, sid, ok))

    async def listed(url, token, *, label="MCP", key=None, timeout=15.0):
        seen["listed"].append(key)
        answer = seen.get("answer", {}).get(key[1], {"tools": [{"name": "t2"}]})
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(own_mcp_store, "set_tools", set_tools)
    monkeypatch.setattr(own_mcp_store, "record_check", record)
    monkeypatch.setattr(own_mcp_client, "list_tools", listed)
    return seen


async def test_a_server_that_answers_gets_its_new_tools(world):
    tally = await S.sweep_own(now=NOW)
    assert ("a@x.com", "s1", ["t2"]) in world["set"]
    assert tally["asked"] == 2


async def test_only_servers_not_checked_in_a_day_are_asked(world):
    await S.sweep_own(now=NOW)
    assert ("a@x.com", "s3") not in world["listed"]


async def test_a_failed_listing_counts_a_failed_check_and_keeps_the_tools(world):
    world["answer"] = {"s1": own_mcp_client.Refused("Your Acme server did not answer.")}
    await S.sweep_own(now=NOW)
    assert ("a@x.com", "s1", False) in world["checks"]
    assert not [s for s in world["set"] if s[1] == "s1"]


async def test_an_answer_with_no_usable_tools_keeps_the_old_ones(world):
    world["answer"] = {"s1": {"tools": []}}
    await S.sweep_own(now=NOW)
    assert ("a@x.com", "s1", False) in world["checks"]
    assert not [s for s in world["set"] if s[1] == "s1"]


async def test_one_server_raising_never_stops_the_others(world):
    world["answer"] = {"s1": RuntimeError("boom")}
    tally = await S.sweep_own(now=NOW)
    assert ("b@x.com", "s2", ["t2"]) in world["set"]
    assert tally["failed"] == 1


async def test_the_store_failing_is_a_quiet_empty_tick(monkeypatch):
    monkeypatch.setattr(own_mcp_store, "all_rows", AsyncMock(side_effect=RuntimeError("db")))
    assert (await S.sweep_own(now=NOW))["asked"] == 0


async def test_the_sweep_tick_includes_own_servers(world, monkeypatch):
    monkeypatch.setattr(S, "_rows", AsyncMock(return_value=[]))
    await S.sweep_once(now=NOW)
    assert world["listed"], "own servers are swept with the connections"


def test_at_most_a_tick_s_worth_is_asked():
    rows = [_row(f"s{i}") for i in range(S.MAX_PER_TICK + 10)]
    assert len(S.own_due(rows, now=NOW)) == S.MAX_PER_TICK
