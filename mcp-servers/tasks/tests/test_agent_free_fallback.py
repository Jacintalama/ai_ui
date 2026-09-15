"""Agents on free models: reasoning off, and the next free model when the
provider fails.

Every test drives agent_runner._chat with a fake _post_chat, the way
test_agent_tool_loop.py does. The failure shapes are the three measured on
production on 2026-09-15: HTTP 400 "Provider returned error", HTTP 200 with
an error object and no choices, and a body with no choices at all.
"""
from unittest.mock import patch

import httpx
import pytest

import agent_runner


def _reply(content="ok", calls=None):
    msg = {"content": content, "tool_calls": calls or None}
    return {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}


def _http_400():
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    resp = httpx.Response(400, json={"detail": "Provider returned error"}, request=req)
    return httpx.HTTPStatusError("400", request=req, response=resp)


def _agent(base="nvidia/nemotron-3-super-120b-a12b:free", system="Be Ada."):
    return {"id": "agent-1", "name": "Ada", "base_model_id": base,
            "params": {"system": system}}


POOL = ["nvidia/nemotron-3-super-120b-a12b:free",
        "nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-mini:free"]


@pytest.fixture(autouse=True)
def _pool(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", list(POOL))
    monkeypatch.setattr(agent_runner, "FREE_REASONING", "none")
    monkeypatch.setattr(agent_runner, "_available_free_ids",
                        _AsyncNone())


class _AsyncNone:
    async def __call__(self):
        return None


async def test_a_free_agent_sends_reasoning_off_and_a_paid_one_does_not():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply()

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(token="t", model="agent-1",
                                 messages=[{"role": "user", "content": "q"}],
                                 tool_ids=None, user_email="o@example.com",
                                 tool_mode="read_only", agent=_agent())
        await agent_runner._chat(token="t", model="agent-2",
                                 messages=[{"role": "user", "content": "q"}],
                                 tool_ids=None, user_email="o@example.com",
                                 tool_mode="read_only", agent=_agent(base="gpt-4o-mini"))
    assert posts[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in posts[1]


async def test_a_provider_failure_moves_the_turn_to_the_next_free_model():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise _http_400()
        return _reply("answered on the fallback")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "system", "content": "identity"},
                      {"role": "user", "content": "q"}],
            tool_ids=["schedules"], user_email="o@example.com",
            tool_mode="read_only", agent=_agent())

    assert answer == "answered on the fallback"
    assert posts[0]["model"] == "agent-1"
    assert posts[1]["model"] == "nex-agi/nex-n2.5-pro:free"
    # Posting the base model directly loses the agent's own instructions,
    # which Open WebUI only applies for the derived model, so they go first.
    assert posts[1]["messages"][0] == {"role": "system", "content": "Be Ada."}
    assert posts[1]["messages"][1]["content"] == "identity"
    assert posts[1]["tool_ids"] == ["schedules"]
    assert posts[1]["reasoning_effort"] == "none"


async def test_a_200_with_an_error_object_counts_as_a_provider_failure():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"error": {"code": 502, "message": "Upstream error"}}
        return _reply("ok")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == "ok"
    assert posts[1]["model"] == "nex-agi/nex-n2.5-pro:free"


async def test_the_turn_stays_on_the_fallback_for_its_later_rounds():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise _http_400()
        if len(posts) == 2:
            return _reply("", calls=[{"id": "c1", "type": "function",
                                       "function": {"name": "list_my_schedules",
                                                    "arguments": "{}"}}])
        return _reply("two schedules")

    async def fake_tool(*a, **k):
        return "[]"

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=fake_tool):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["schedules"], user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == "two schedules"
    assert [p["model"] for p in posts] == [
        "agent-1", "nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-pro:free"]


async def test_a_spent_pool_answers_with_the_busy_sentence_not_an_exception():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == agent_runner.FREE_POOL_EXHAUSTED
    assert len(posts) == 3, "each pool id is tried exactly once"


async def test_a_paid_agent_never_falls_back():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         pytest.raises(httpx.HTTPStatusError):
        await agent_runner._chat(
            token="t", model="agent-2", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent(base="gpt-4o-mini"))
    assert len(posts) == 1


async def test_no_agent_row_means_the_old_behaviour_exactly():
    """Callers that predate this (tests, the summariser) pass no agent."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         pytest.raises(httpx.HTTPStatusError):
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only")
    assert len(posts) == 1 and "reasoning_effort" not in posts[0]


async def test_withdrawn_pool_ids_are_skipped_when_the_catalogue_is_known(monkeypatch):
    async def catalogue():
        return {"nvidia/nemotron-3-super-120b-a12b:free", "nex-agi/nex-n2.5-mini:free"}
    monkeypatch.setattr(agent_runner, "_available_free_ids", catalogue)
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise _http_400()
        return _reply("ok")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert posts[1]["model"] == "nex-agi/nex-n2.5-mini:free"
