"""Every new schedule gets an agent, even when the client cannot name one.

A schedule with no agent fails every time it fires (see scheduler.NO_AGENT).
The cron page now refuses to create one, but the bots cannot: webhook-handler's
create_schedule has no agent_id parameter at all, so a schedule made from
Discord or Slack could only ever be a dead one.

Nothing can guess which agent somebody meant, but "the one they have had
longest" is a defensible answer and a recorded one: it lands on the row, shows
on the card, and can be changed. That is better than a schedule nobody runs,
and better than a cron panel that cannot create anything.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from models import Schedule

pytestmark = pytest.mark.anyio if False else []

ADA = {"id": "agent-ada-0001", "name": "Ada", "created_at": 100}
MIA = {"id": "agent-mia-0002", "name": "Mia", "created_at": 200}


def _client(monkeypatch, agents, rows=()):
    """A TestClient whose DB accepts writes and whose agent listing is `agents`.

    Mirrors the _FakeSession shape in test_schedule_limits.py rather than
    inventing a third one.
    """
    from main import app

    created: list = []

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj):
            if isinstance(obj, Schedule):
                created.append(obj)
        async def commit(self): return None
        async def execute(self, stmt):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self_): return list(rows)
                    return _S()
                def scalar_one_or_none(self): return None
            return _R()

    monkeypatch.setattr("routes_schedules.session", lambda: _FakeSession())

    async def _agents(email):
        return list(agents)

    monkeypatch.setattr("routes_schedules._agents_for_owner", _agents)
    return TestClient(app, raise_server_exceptions=False), created


def _body(**kw):
    b = {"name": "n", "cron_expr": "0 9 * * *", "prompt": "give me a quote"}
    b.update(kw)
    return b


HEADERS = {"X-User-Email": "o@example.com"}


def test_a_schedule_created_without_an_agent_gets_one(monkeypatch):
    """The whole point. A bot cannot name an agent, and a schedule without
    one cannot run."""
    c, created = _client(monkeypatch, [MIA, ADA])

    r = c.post("/schedules", json=_body(), headers=HEADERS)

    assert r.status_code == 201, r.text
    assert created and created[0].agent_id == "agent-ada-0001"


def test_the_agent_it_picks_is_the_one_held_longest(monkeypatch):
    """Not the first row the listing happened to return. Ada is seeded before
    Mia for every user, so the oldest is the one people think of as theirs."""
    c, created = _client(monkeypatch, [MIA, ADA])

    c.post("/schedules", json=_body(), headers=HEADERS)

    assert created[0].agent_id == ADA["id"]


def test_naming_an_agent_still_wins(monkeypatch):
    """The default must never override somebody's actual choice."""
    c, created = _client(monkeypatch, [MIA, ADA])

    c.post("/schedules", json=_body(agent_id="agent-mia-0002"), headers=HEADERS)

    assert created[0].agent_id == "agent-mia-0002"


def test_the_response_names_who_will_run_it(monkeypatch):
    """So a bot can say "Ada will run this" instead of leaving the person to
    find out at 7pm."""
    c, _created = _client(monkeypatch, [ADA])

    r = c.post("/schedules", json=_body(), headers=HEADERS)

    assert r.json()["agent_id"] == "agent-ada-0001"
    assert r.json()["agent_name"] == "Ada"


def test_somebody_with_no_agents_is_told_rather_than_given_a_dead_schedule(
        monkeypatch):
    """_agents_for returns [] on any doubt, including a listing cut short, so
    this cannot tell "none" from "could not check". Either way creating the
    schedule would produce one that never runs, and the person is right here
    to be told."""
    c, created = _client(monkeypatch, [])

    r = c.post("/schedules", json=_body(), headers=HEADERS)

    assert r.status_code == 400, r.text
    assert created == []
    assert "agent" in r.json()["detail"].lower()


def test_a_video_schedule_needs_no_agent(monkeypatch):
    """kind=video renders a walkthrough and never reaches the agent path, so
    requiring one would block a feature that works."""
    c, created = _client(monkeypatch, [])

    r = c.post("/schedules",
               json=_body(kind="video",
                          video_config={"url": "https://example.com"}),
               headers=HEADERS)

    assert r.status_code == 201, r.text
    assert created and created[0].agent_id is None
