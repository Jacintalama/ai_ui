"""The plain debug page: what the agents decided and did, as tables.

The owner asked for a troubleshooting view that shows the agents talking to
each other, plainer than the office (call, 2026-10-16). These tests pin what
a person reads there and that it never breaks the page when a read fails.
"""
import datetime as dt
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes_agent_debug as page

EMAIL = "debug-owner@example.com"
T = dt.datetime(2026, 10, 20, 9, 30, 5, tzinfo=dt.timezone.utc)
NAMES = {"agent-a": "Ada", "agent-m": "Mia"}

DATA = {
    "decisions": [{"created_at": T, "provider": "jev", "model": "jev-1.13.0",
                   "kind": "answer", "kind_confidence": 0.96,
                   "agent_id": "agent-m", "agent_confidence": 0.67,
                   "path": "fallback", "reason": "low confidence", "ms": 281,
                   "input_tokens": 436, "cost_usd": Decimal("0.00001831")}],
    "runs": [{"started_at": T, "agent_id": "agent-a", "source": "chat",
              "model": "z-ai/glm-5.3-flash", "status": "completed",
              "secs": 4.9, "cost_usd": 0.00013}],
    "asks": [{"started_at": T, "agent_id": "agent-a",
              "target_agent_id": "agent-m", "status": "ok"}],
    "jobs": [{"created_at": T, "status": "done", "lead_agent_id": "agent-a",
              "done": 2, "total": 3}],
}


def _client(monkeypatch, data=DATA, names=NAMES):
    seen = []

    async def read(email):
        seen.append(email)
        return data

    async def roster(email):
        return names

    monkeypatch.setattr(page, "_read", read)
    monkeypatch.setattr(page, "_names", roster)
    app = FastAPI()
    app.include_router(page.router)
    return TestClient(app), seen


def test_the_page_needs_a_signed_in_person(monkeypatch):
    c, _ = _client(monkeypatch)
    assert c.get("/tasks/agents/debug").status_code == 401


def test_the_page_reads_only_the_signed_in_persons_records(monkeypatch):
    c, seen = _client(monkeypatch)
    r = c.get("/tasks/agents/debug", headers={"X-User-Email": EMAIL})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert seen == [EMAIL]


def test_a_decision_shows_its_choice_confidence_and_path():
    html = page.render_page(DATA, NAMES)
    assert "Jev decisions" in html
    assert "fallback" in html and "low confidence" in html
    assert "answer 0.96" in html
    assert "Mia 0.67" in html
    assert "281 ms" in html
    assert "$0.000018" in html
    assert "2026-10-20 09:30:05" in html


def test_runs_asks_and_jobs_are_shown_with_names():
    html = page.render_page(DATA, NAMES)
    assert "z-ai/glm-5.3-flash" in html and "4.9 s" in html
    assert "$0.000130" in html
    assert "Ada asked Mia" in html
    assert "2 of 3 steps" in html


def test_an_unknown_agent_is_shown_by_its_id():
    html = page.render_page(DATA, {})
    assert "agent-m 0.67" in html


def test_every_value_is_escaped():
    data = dict(DATA, decisions=[dict(DATA["decisions"][0],
                                      reason="<script>x</script>")])
    html = page.render_page(data, {"agent-m": "<b>Mia</b>"})
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "<b>Mia</b>" not in html


def test_an_empty_table_says_so():
    html = page.render_page({"decisions": [], "runs": [], "asks": [],
                             "jobs": []}, {})
    assert html.count("None yet.") == 4


def test_a_table_that_could_not_be_read_says_so(monkeypatch):
    data = dict(DATA, decisions=None)
    c, _ = _client(monkeypatch, data=data)
    r = c.get("/tasks/agents/debug", headers={"X-User-Email": EMAIL})
    assert r.status_code == 200
    assert "Could not read" in r.text
    assert "z-ai/glm-5.3-flash" in r.text


def test_the_page_is_plain():
    html = page.render_page(DATA, NAMES)
    assert "animation" not in html and "@keyframes" not in html
    assert "<script" not in html


def test_the_service_serves_the_page(monkeypatch):
    import os
    if not os.environ.get("AIUI_FERNET_KEY"):
        from cryptography.fernet import Fernet
        monkeypatch.setenv("AIUI_FERNET_KEY", Fernet.generate_key().decode())
    from main import app
    # Asked of the app, not read off app.routes (see the same test in
    # test_routes_agent_jobs): served refuses a stranger, missing is a 404.
    assert TestClient(app).get("/tasks/agents/debug").status_code == 401


def test_the_agents_page_links_to_it():
    import pathlib
    agents = (pathlib.Path(page.__file__).parent / "static" / "agents.html"
              ).read_text(encoding="utf-8")
    assert 'href="/tasks/agents/debug"' in agents


def test_the_queries_match_email_in_any_case():
    """Some agent rows were stored with the email as typed (agent_activity
    reads them with lower() for that reason)."""
    for query in (page._RUNS, page._ASKS, page._JOBS):
        assert "lower(" in query and "lower(:email)" in query
