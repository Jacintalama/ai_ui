"""Asking the tasks service to run an agent turn.

The one thing that is easy to get wrong here is the timeout. TasksClient
defaults to 15 seconds, which is right for reading a row and far too short
for a turn that may run three rounds of tool use.
"""
import json

import httpx
import pytest
import respx

from clients.tasks import AGENT_TURN_TIMEOUT_SECONDS, TasksAPIError, TasksClient

BASE = "http://tasks:8210"


def _client():
    return TasksClient(BASE, internal_secret="sekrit")


@respx.mock
async def test_a_turn_is_asked_for_with_the_internal_secret():
    route = respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(200, json={"answer": "hi", "notes": []}))

    out = await _client().agent_turn(
        user_email="owner@example.com", agent_id="agent-1",
        messages=[{"role": "user", "content": "q"}])

    assert out == {"answer": "hi", "notes": []}
    sent = route.calls[0].request
    assert sent.headers["X-Internal-Secret"] == "sekrit"
    # Never X-User-Email on this call: the body names the user, and the
    # endpoint is internal. See the note on TasksClient._headers.
    assert "X-User-Email" not in sent.headers


@respx.mock
async def test_the_turn_gets_longer_than_the_default_fifteen_seconds():
    """Three rounds of tool use does not fit in the timeout used for reading
    a schedule row, and a timeout here reads to the user as the bot ignoring
    them."""
    seen = {}

    def capture(request):
        seen["timeout"] = request.extensions.get("timeout", {}).get("read")
        return httpx.Response(200, json={"answer": "hi", "notes": []})

    respx.post(f"{BASE}/agents/turn").mock(side_effect=capture)
    await _client().agent_turn(
        user_email="o@e.com", agent_id="a", messages=[])

    assert seen["timeout"] == AGENT_TURN_TIMEOUT_SECONDS
    assert AGENT_TURN_TIMEOUT_SECONDS > 15


@respx.mock
async def test_a_pending_answer_is_passed_straight_through():
    respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(200, json={"pending": {"calls": [1]}}))

    out = await _client().agent_turn(
        user_email="o@e.com", agent_id="a", messages=[])
    assert out["pending"]["calls"] == [1]


@respx.mock
async def test_a_resume_carries_the_verdict():
    route = respx.post(f"{BASE}/agents/turn/resume").mock(
        return_value=httpx.Response(200, json={"answer": "sent", "notes": []}))

    await _client().agent_turn_resume(
        user_email="o@e.com", agent_id="a",
        conversation=[{"role": "user", "content": "x"}],
        calls=[{"id": "c1"}], approved=False)

    body = route.calls[0].request.content.decode()
    assert '"approved": false' in body or '"approved":false' in body


@respx.mock
async def test_a_failure_arrives_as_a_typed_error_the_pipeline_can_catch():
    """pipeline.handle_event turns TasksAPIError into a sentence. An untyped
    exception here would escape as UNEXPECTED instead."""
    respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(503, json={"detail": "nope"}))

    with pytest.raises(TasksAPIError):
        await _client().agent_turn(
            user_email="o@e.com", agent_id="a", messages=[])


# --- the outgoing body, exactly -------------------------------------------
#
# respx only matched on URL and method above, so nothing caught a payload
# regression. tool_ids is the field that matters most here: the tasks
# service resolves an agent's own tools from its agent_id, and that field is
# what gates which tools may actually run. Sending it from the gateway would
# move that decision out of the service that enforces it, so its absence is
# asserted explicitly, not just the shape of what IS sent.

@respx.mock
async def test_the_turn_body_sends_exactly_user_email_agent_id_and_messages():
    route = respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(200, json={"answer": "hi", "notes": []}))

    await _client().agent_turn(
        user_email="owner@example.com", agent_id="agent-1",
        messages=[{"role": "user", "content": "q"}])

    body = json.loads(route.calls[0].request.content)
    assert set(body.keys()) == {"user_email", "agent_id", "messages"}
    assert body["user_email"] == "owner@example.com"
    assert body["agent_id"] == "agent-1"
    assert body["messages"] == [{"role": "user", "content": "q"}]
    assert "tool_ids" not in body


@respx.mock
async def test_the_resume_body_sends_exactly_its_five_fields():
    route = respx.post(f"{BASE}/agents/turn/resume").mock(
        return_value=httpx.Response(200, json={"answer": "sent", "notes": []}))

    await _client().agent_turn_resume(
        user_email="owner@example.com", agent_id="agent-1",
        conversation=[{"role": "user", "content": "x"}],
        calls=[{"id": "c1"}], approved=False)

    body = json.loads(route.calls[0].request.content)
    assert set(body.keys()) == {
        "user_email", "agent_id", "conversation", "calls", "approved"}
    assert body["user_email"] == "owner@example.com"
    assert body["agent_id"] == "agent-1"
    assert body["conversation"] == [{"role": "user", "content": "x"}]
    assert body["calls"] == [{"id": "c1"}]
    assert body["approved"] is False
    assert "tool_ids" not in body
