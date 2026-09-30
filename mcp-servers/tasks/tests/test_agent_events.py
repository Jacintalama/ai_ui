"""The live office's fan-out: right person, no prose, never costs a turn."""
import asyncio
import json

import pytest

import agent_events

ALLOWED = {"event", "agent_id", "tool", "target_agent_id", "status", "at"}


@pytest.fixture(autouse=True)
def _empty_bus():
    agent_events._SUBS.clear()
    yield
    agent_events._SUBS.clear()


def test_an_event_reaches_every_page_of_its_owner_and_nobody_else():
    mine_1 = agent_events.subscribe("me@example.com")
    mine_2 = agent_events.subscribe("me@example.com")
    theirs = agent_events.subscribe("them@example.com")

    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com")

    assert mine_1.queue.qsize() == 1
    assert mine_2.queue.qsize() == 1
    assert theirs.queue.qsize() == 0


def test_a_subscriber_that_raises_does_not_reach_the_publisher():
    class Broken:
        def put_nowait(self, _):
            raise RuntimeError("boom")
    bad = agent_events.subscribe("me@example.com")
    bad.queue = Broken()
    good = agent_events.subscribe("me@example.com")

    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com")        # must not raise

    assert good.queue.qsize() == 1


def test_a_full_page_is_dropped_and_the_others_keep_receiving(monkeypatch):
    monkeypatch.setattr(agent_events, "MAX_QUEUE", 2)
    slow = agent_events.subscribe("me@example.com")
    monkeypatch.setattr(agent_events, "MAX_QUEUE", 100)
    fast = agent_events.subscribe("me@example.com")

    for _ in range(3):
        agent_events.publish("tool_started", agent_id="agent-a",
                             user_email="me@example.com", tool="search_drive")

    assert slow.dropped is True
    assert slow not in agent_events._SUBS.get("me@example.com", set())
    assert fast.queue.qsize() == 3


@pytest.mark.parametrize("event", sorted(agent_events.EVENTS))
def test_each_event_carries_only_names_and_never_the_owner(event):
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish(event, agent_id="agent-a", user_email="me@example.com",
                         tool="ask_colleague", target_agent_id="agent-b",
                         status="ok")
    payload = sub.queue.get_nowait()
    assert payload["event"] == event
    assert set(payload) <= ALLOWED
    assert "me@example.com" not in json.dumps(payload)


def test_an_unknown_event_is_not_sent():
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish("question_asked", agent_id="agent-a",
                         user_email="me@example.com")
    assert sub.queue.qsize() == 0


async def test_the_stream_says_hello_then_delivers_then_ends_when_dropped():
    gen = agent_events.stream("me@example.com", poll_seconds=0.05)
    first = await gen.__anext__()
    assert first["event"] == "hello"

    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com")
    nxt = await asyncio.wait_for(gen.__anext__(), 1)
    assert nxt["event"] == "run_started"
    assert json.loads(nxt["data"])["agent_id"] == "agent-a"

    (sub,) = agent_events._SUBS["me@example.com"]
    sub.dropped = True
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 1)
    assert "me@example.com" not in agent_events._SUBS
