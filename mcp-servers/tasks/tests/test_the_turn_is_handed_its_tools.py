"""A turn is handed the tools it needs instead of spending rounds finding
them.

Measured on production 2026-11-09, one turn of Ralph's, from
tasks.agent_step:

    09:08:27.4  search_tools    ok
    09:08:28.7  describe_tools  ok
    09:08:32.8  search_tools    ok
    09:08:33.7  describe_tools  ok
    09:08:34.7  search_tools    ok
    09:08:36.0  call_tool       failed
    09:08:37.7  call_tool       ok
    -> "Stopped after 7 rounds of tool use, so this answer may be incomplete."

`rounds += 1` happens once per MODEL round trip, so the budget of 7 is
seven conversations with the model, and five of them went on finding out
which tools exist. Discovery is sequential by construction: search, read
the names, describe, read the fields, then call. With roughly 300 tools
behind one search gateway, a four step job needs four discoveries and
four calls, which is eight round trips against a budget of seven. It
cannot finish, whatever the person types.

The cap is not the cause. Its comment sizes it as "at 60 seconds each the
rounds are seven minutes", and these rounds took about two seconds: the
whole turn above ran in 17.9 seconds and still hit the ceiling.

So the turn is handed the candidates up front. One search and one
describe, made by us before the model is asked anything, cost no round at
all, and the model can call the tool on its first move.

It is a hint, not a restriction. `search_tools` stays available, the
hint is dropped silently whenever the proxy cannot answer, and nothing
about what the agent may DO changes: access level and approvals are
unaffected, because this only tells it what exists.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

import agent_runner
import agent_tools as T

FOUND = [
    {"tool_name": "my-clickup_create_task", "server_id": "my-clickup",
     "description": "Create Task. Create a new task."},
    {"tool_name": "my-clickup_get_spaces", "server_id": "my-clickup",
     "description": "Get Spaces. View the Spaces in a Workspace."},
]

DESCRIBED = [
    {"tool_name": "my-clickup_create_task",
     "description": "Create Task. Create a new task.",
     "request_body": {"content": {"application/json": {"schema": {
         "anyOf": [{"properties": {"list_id": {"type": "string"},
                                   "name": {"type": "string"},
                                   "assignees": {"type": "array"}},
                    "required": ["list_id", "name"]},
                   {"type": "null"}]}}}}},
    {"tool_name": "my-clickup_get_spaces",
     "description": "Get Spaces. View the Spaces in a Workspace.",
     "request_body": {"content": {"application/json": {"schema": {
         "anyOf": [{"properties": {"team_id": {"type": "string"}},
                    "required": ["team_id"]},
                   {"type": "null"}]}}}}},
]


# --- the hint itself, no I/O --------------------------------------------

def test_the_hint_names_the_tools_that_were_found():
    said = T.tool_hint(FOUND, DESCRIBED)
    assert "my-clickup_create_task" in said, said
    assert "my-clickup_get_spaces" in said, said


def test_the_hint_says_what_each_tool_requires():
    """The second half of the cost: without this the model must call
    describe_tools, which is another round trip per tool."""
    said = T.tool_hint(FOUND, DESCRIBED)
    assert "list_id" in said and "name" in said, said
    assert "team_id" in said, said


def test_the_hint_leaves_out_the_optional_fields():
    """Required only. The whole schema is what makes describe_tools
    expensive, and an optional field the model does not need is noise it
    has to read past."""
    said = T.tool_hint(FOUND, DESCRIBED)
    assert "assignees" not in said, said


def test_the_hint_says_how_to_run_them():
    """A list of names it cannot act on would be worth nothing. Every
    proxy tool goes through call_tool."""
    said = T.tool_hint(FOUND, DESCRIBED).lower()
    assert "call_tool" in said, said


def test_a_tool_with_no_required_fields_is_still_offered():
    found = [{"tool_name": "my-clickup_whoami", "description": "Who am I."}]
    described = [{"tool_name": "my-clickup_whoami", "request_body": {}}]
    said = T.tool_hint(found, described)
    assert "my-clickup_whoami" in said, said


def test_a_tool_that_was_found_but_not_described_is_still_named():
    """describe_tools can answer for fewer tools than search found. Naming
    it without its fields still saves the search."""
    said = T.tool_hint(FOUND, DESCRIBED[:1])
    assert "my-clickup_get_spaces" in said, said


def test_nothing_found_is_no_hint_at_all():
    """An empty block in front of every turn is noise on every turn."""
    assert T.tool_hint([], []) == ""
    assert T.tool_hint(None, None) == ""


@pytest.mark.parametrize("junk", [
    "not a list", 42, [None], [{"no_name": 1}], [{"tool_name": ""}],
    [{"tool_name": 7}],
])
def test_junk_never_raises(junk):
    """These come off the wire from another service."""
    assert isinstance(T.tool_hint(junk, junk), str)


def test_the_hint_is_bounded():
    """It goes in front of every turn and is re-posted on every round, so
    it cannot grow with the catalogue."""
    many = [{"tool_name": "my-clickup_t%d" % i,
             "description": "x" * 400} for i in range(40)]
    said = T.tool_hint(many, [])
    assert len(said) < 2000, len(said)


# --- fetching it ---------------------------------------------------------

async def test_one_search_and_one_describe_and_no_model_round():
    """The point of the change: this costs HTTP calls, not rounds."""
    seen = []

    async def fake_post(url, json=None, headers=None, timeout=None):
        seen.append(url)

        class R:
            status_code = 200

            @staticmethod
            def json():
                if url.endswith("/meta/search_tools"):
                    return {"results": FOUND}
                return {"tools": DESCRIBED}
        return R()

    with patch("agent_tools._post_json", new=fake_post):
        said = await T.tools_for_message("owner@example.com",
                                         "create a clickup task")
    assert "my-clickup_create_task" in said, said
    assert sum(1 for u in seen if u.endswith("/meta/search_tools")) == 1, seen
    assert sum(1 for u in seen if u.endswith("/meta/describe_tools")) == 1, seen


async def test_a_proxy_that_cannot_answer_costs_the_turn_nothing():
    """It is a hint. A turn must never fail because the hint failed."""
    async def boom(url, json=None, headers=None, timeout=None):
        raise RuntimeError("proxy down")

    with patch("agent_tools._post_json", new=boom):
        said = await T.tools_for_message("owner@example.com", "anything")
    assert said == ""


async def test_no_message_means_no_search():
    async def fake_post(url, json=None, headers=None, timeout=None):
        raise AssertionError("searched with nothing to search for")

    with patch("agent_tools._post_json", new=fake_post):
        assert await T.tools_for_message("owner@example.com", "   ") == ""


# --- in the turn ---------------------------------------------------------

def _reply(content=None, calls=None):
    message = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if calls is not None:
        message["tool_calls"] = calls
    return {"choices": [{"message": message}]}


async def test_the_model_is_told_before_it_is_asked_anything():
    posted = {}

    async def fake_post(payload, token, timeout=None):
        posted.setdefault("first", payload.get("messages"))
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch.object(agent_runner, "_tools_for_message",
                      new=AsyncMock(return_value="USE my-clickup_create_task")):
        await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "create a clickup task"}],
            tool_ids=["server:mcp-proxy"], user_email="owner@example.com",
            tool_mode="read_only")

    flat = json.dumps(posted.get("first") or [])
    assert "my-clickup_create_task" in flat, flat


async def test_an_agent_without_the_proxy_is_not_searched_for():
    """Gmail and the calendar are declared to the model directly. Only the
    proxy hides its tools behind a search."""
    looked = AsyncMock(return_value="SHOULD NOT APPEAR")

    async def fake_post(payload, token, timeout=None):
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch.object(agent_runner, "_tools_for_message", new=looked):
        await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "read my email"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    looked.assert_not_awaited()


async def test_a_turn_still_runs_when_the_hint_is_empty():
    async def fake_post(payload, token, timeout=None):
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch.object(agent_runner, "_tools_for_message",
                      new=AsyncMock(return_value="")):
        answer, _notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "hello"}],
            tool_ids=["server:mcp-proxy"], user_email="owner@example.com",
            tool_mode="read_only")
    assert answer == "done"
