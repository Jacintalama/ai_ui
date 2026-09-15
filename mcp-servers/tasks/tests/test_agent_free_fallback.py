"""Agents on free models: reasoning off, and the next free model when the
provider fails.

Every test drives agent_runner._chat with a fake _post_chat, the way
test_agent_tool_loop.py does. The failure shapes are the three measured on
production on 2026-09-15: HTTP 400 "Provider returned error", HTTP 200 with
an error object and no choices, and a body with no choices at all.
"""
import logging
from unittest.mock import patch

import httpx
import pytest

import agent_runner

#: Captured before the autouse fixture below replaces it with a stub, so the
#: catalogue test can drive the real function.
_real_available_free_ids = agent_runner._available_free_ids


def _reply(content="ok", calls=None):
    msg = {"content": content, "tool_calls": calls or None}
    return {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}


def _http_400():
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    resp = httpx.Response(400, json={"detail": "Provider returned error"}, request=req)
    return httpx.HTTPStatusError("400", request=req, response=resp)


def _http_401():
    req = httpx.Request("POST", "http://open-webui:8080/api/chat/completions")
    resp = httpx.Response(401, json={"detail": "Not authenticated"}, request=req)
    return httpx.HTTPStatusError("401", request=req, response=resp)


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
    # Prepended fresh each post, never folded into the carried conversation:
    # a turn that ran ten rounds on the fallback would otherwise send the
    # agent's instructions ten times.
    system_first = {"role": "system", "content": "Be Ada."}
    assert sum(1 for m in posts[2]["messages"] if m == system_first) == 1


async def test_a_spent_pool_answers_with_the_busy_sentence_not_an_exception(caplog):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_400()

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         caplog.at_level(logging.WARNING, logger="agent_runner"):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == agent_runner.FREE_POOL_EXHAUSTED
    assert len(posts) == 3, "each pool id is tried exactly once"
    # The busy sentence reads like an answer. Without this line a turn that
    # reached nobody leaves no trace at all, because _post_chat logs nothing
    # for a timeout and the exception is deliberately swallowed here.
    assert "free pool spent for agent-1" in caplog.text
    assert "nex-agi/nex-n2.5-mini:free" in caplog.text


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


# --- the shapes that are not an HTTP 400 ------------------------------------

async def test_a_timeout_on_a_free_model_moves_to_the_next_id():
    """An overloaded free provider often does not answer at all rather than
    answering an error, so the timeout is the failure shape, and _post_chat
    raises it without logging anything."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            raise httpx.ReadTimeout("no answer in time")
        return _reply("answered after the timeout")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == "answered after the timeout"
    assert posts[1]["model"] == "nex-agi/nex-n2.5-pro:free"


async def test_a_timeout_on_a_paid_model_propagates():
    """A paid agent has no pool to move to, so the caller has to see it."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise httpx.ReadTimeout("no answer in time")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         pytest.raises(httpx.ReadTimeout):
        await agent_runner._chat(
            token="t", model="agent-2", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent(base="gpt-4o-mini"))
    assert len(posts) == 1


async def test_a_401_must_not_spend_the_pool():
    """An expired chat token is this service's own problem and every model
    in the pool would refuse it the same way. Trying all three would waste
    two completions and then blame the free providers for it."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        raise _http_401()

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         pytest.raises(httpx.HTTPStatusError):
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert len(posts) == 1


async def test_a_body_with_an_answer_and_an_error_note_is_an_answer():
    """Choices first. A body that carries a completion and also mentions an
    upstream it retried is an answer, and throwing it away would cost the
    person the reply and the pool an id."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        body = _reply("here it is")
        body["error"] = {"code": 502, "message": "one upstream was retried"}
        return body

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == "here it is"
    assert len(posts) == 1


async def test_a_body_that_is_not_a_dict_counts_as_a_provider_failure():
    """A 2xx carrying anything but an object reaches data.get and raises
    AttributeError, which takes the whole turn down instead of moving it to
    the next id and, at the end, saying the pool is busy."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return ["not", "a", "body"]

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=_agent())
    assert answer == agent_runner.FREE_POOL_EXHAUSTED
    assert len(posts) == 3


# --- the catalogue probe ----------------------------------------------------

async def test_an_unreachable_catalogue_is_not_probed_again_this_quarter_hour(
        monkeypatch):
    """The probe sits in front of the person's first token and its client
    waits up to 10 seconds. Retrying it on every turn while OpenRouter is
    unreachable spends that on every turn, for a list that is only used to
    skip withdrawn ids."""
    attempts = []

    class _Refuses:
        def __init__(self, *a, **k):
            attempts.append(1)

        async def __aenter__(self):
            raise httpx.ConnectError("no route to openrouter")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(agent_runner.httpx, "AsyncClient", _Refuses)
    monkeypatch.setattr(agent_runner, "_available_ids", None)
    monkeypatch.setattr(agent_runner, "_available_at", 0.0)

    first = await _real_available_free_ids()
    second = await _real_available_free_ids()

    assert first is None and second is None, "a failed read must not filter"
    assert len(attempts) == 1, "the catalogue was probed twice inside the TTL"
