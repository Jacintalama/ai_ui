# mcp-servers/tasks/tests/test_routes_aiuibuilder.py
"""User-scoped one-shot build endpoint (/api/aiuibuilder)."""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
import routes_aiuibuilder as rb

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


def test_slugify_basic():
    assert rb._slugify("A Todo List With Dark Mode") == "a-todo-list-with-dark"


def test_slugify_strips_punctuation_and_empty_fallback():
    assert rb._slugify("!!!  ") == "app"
    assert rb._slugify("My App!!! v2") == "my-app-v2"


def test_make_slug_has_suffix_and_matches_route_regex():
    s = rb._make_slug("Todo List")
    assert s.startswith("todo-list-")
    assert _SLUG_RE.match(s)
    assert re.search(r"-[0-9a-f]{4}$", s)


def test_public_build_status_mapping():
    assert rb._public_build_status("completed") == "completed"
    assert rb._public_build_status("failed") == "failed"
    # awaiting_input is terminal for Discord (agent exited, no answer path).
    assert rb._public_build_status("awaiting_input") == "needs_input"
    # Only actively-running states map to "running".
    for s in ("running", "planning"):
        assert rb._public_build_status(s) == "running"
    # Dead-end states a Discord build can't progress from → failed.
    for s in ("pending", "claimed_manual", "weird-unknown"):
        assert rb._public_build_status(s) == "failed"


def test_live_build_states_excludes_awaiting_input():
    # awaiting_input must NOT count toward the concurrency guard, or one
    # ambiguous build would 429-lock the platform forever.
    assert "awaiting_input" not in rb._LIVE_BUILD_STATES
    assert "running" in rb._LIVE_BUILD_STATES


def test_preview_url_shape():
    assert rb._preview_url("todo-a1b2") == (
        "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/"
    )


def test_bind_slug_description_pins_the_slug():
    out = rb._bind_slug_description("todo-a1b2", "a todo list with dark mode")
    # The directive must name the exact slug + path so the agent can't pick its own.
    assert 'PROJECT NAME: "todo-a1b2"' in out
    assert "apps/todo-a1b2/" in out
    # The user's request is preserved after the directive.
    assert "a todo list with dark mode" in out
    assert out.index('PROJECT NAME') < out.index("a todo list")


def test_bind_slug_description_caps_length():
    out = rb._bind_slug_description("s-a1b2", "x" * 30000)
    assert len(out) == 20_000


from unittest.mock import AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def test_build_requires_email():
    r = _client().post("/api/aiuibuilder/build", json={"description": "a todo app"})
    assert r.status_code == 401


def test_build_happy_path(monkeypatch):
    async def fake_create(email, seed, description, template_key=None):
        assert email == "alice@x.com"
        return ("11111111-1111-1111-1111-111111111111", "todo-list-a1b2")
    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)

    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "a todo list with dark mode"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "todo-list-a1b2"
    assert body["status"] == "running"
    assert body["task_id"] == "11111111-1111-1111-1111-111111111111"


def test_build_busy_returns_429(monkeypatch):
    async def busy(email, seed, description, template_key=None):
        raise HTTPException(status_code=429, detail="A build is already running")
    monkeypatch.setattr(rb, "_create_and_spawn_build", busy)

    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "another app"},
    )
    assert r.status_code == 429


def test_build_validation_empty_description(monkeypatch):
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": ""},
    )
    assert r.status_code == 422


import types


def _fake_item(status, slug, result=None, assignee="alice@x.com"):
    return types.SimpleNamespace(
        status=status, built_app_slug=slug, result=result, assignee_email=assignee,
    )


def test_build_status_requires_email():
    r = _client().get("/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 401


def test_build_status_unknown_or_other_user_404(monkeypatch):
    async def load_none(email, task_id):
        return None
    monkeypatch.setattr(rb, "_load_owned_build", load_none)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    assert r.status_code == 404


def test_build_status_completed_has_preview(monkeypatch):
    async def load(email, task_id):
        return _fake_item("completed", "todo-a1b2")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["preview_url"] == "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/"
    assert body["error"] is None


def test_build_status_failed_has_error_no_preview(monkeypatch):
    async def load(email, task_id):
        return _fake_item("failed", "todo-a1b2", result="agent crashed: boom")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert body["preview_url"] is None
    assert "boom" in body["error"]


def test_build_status_running_no_preview(monkeypatch):
    async def load(email, task_id):
        return _fake_item("running", "todo-a1b2")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    body = r.json()
    assert body["status"] == "running"
    assert body["preview_url"] is None


def test_build_status_awaiting_input_maps_needs_input(monkeypatch):
    # An ambiguous build the agent paused on: terminal for Discord, surfaces
    # the clarifying question, no preview, and (crucially) is not "running".
    async def load(email, task_id):
        return _fake_item("awaiting_input", "todo-a1b2",
                          result="Which color theme — light or dark?")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    body = r.json()
    assert body["status"] == "needs_input"
    assert body["preview_url"] is None
    assert "color theme" in body["error"]


def test_build_status_pending_maps_failed(monkeypatch):
    # The agent-pipeline exception path leaves a build in `pending`; for Discord
    # that's a dead build → failed (so the watcher stops, not "still building").
    async def load(email, task_id):
        return _fake_item("pending", "todo-a1b2", result="Previous AI run failed: boom")
    monkeypatch.setattr(rb, "_load_owned_build", load)
    r = _client().get(
        "/api/aiuibuilder/build/11111111-1111-1111-1111-111111111111",
        headers={"X-User-Email": "alice@x.com"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert body["preview_url"] is None


def test_compose_build_description_template_less_matches_bind():
    out = rb._compose_build_description("todo-a1b2", None, "a todo list")
    assert out == rb._bind_slug_description("todo-a1b2", "a todo list")
    assert 'PROJECT NAME: "todo-a1b2"' in out
    assert "USER REQUEST:" in out
    assert "a todo list" in out


def test_compose_build_description_with_template_injects_rules():
    out = rb._compose_build_description("port-a1b2", "portfolio", "a UX designer named Maya")
    assert 'PROJECT NAME: "port-a1b2"' in out
    assert "USER REQUEST:" in out
    assert "a UX designer named Maya" in out
    assert "PURPOSE:" in out
    assert out.index('PROJECT NAME') < out.index("PURPOSE:") < out.index("USER REQUEST:")


def test_compose_build_description_caps_length():
    out = rb._compose_build_description("s-a1b2", "portfolio", "x" * 30000)
    assert len(out) == 20_000


def test_templates_catalog_requires_email():
    r = _client().get("/api/aiuibuilder/templates")
    assert r.status_code == 401


def test_templates_catalog_shape_and_excludes_blank_custom():
    r = _client().get("/api/aiuibuilder/templates", headers={"X-User-Email": "a@x.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {t["key"] for t in body}
    assert "portfolio" in keys
    assert "blank" not in keys and "custom" not in keys
    assert all("rules" not in t for t in body)
    for t in body:
        assert set(t) >= {"key", "label", "emoji", "description", "has_app", "note"}


def test_templates_catalog_notes():
    r = _client().get("/api/aiuibuilder/templates", headers={"X-User-Email": "a@x.com"})
    by_key = {t["key"]: t for t in r.json()}
    assert "Supabase" in by_key["auth"]["note"]
    assert by_key["crud"]["note"] == "saves in your browser"
    assert by_key["portfolio"]["note"] == ""


def test_build_accepts_template_key(monkeypatch):
    seen = {}
    async def fake_create(email, seed, description, template_key=None):
        seen["template_key"] = template_key
        return ("11111111-1111-1111-1111-111111111111", "portfolio-a1b2")
    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "a designer site", "template_key": "portfolio"},
    )
    assert r.status_code == 201, r.text
    assert seen["template_key"] == "portfolio"


def test_build_invalid_template_key_422():
    # Exercises REAL _create_and_spawn_build: validation must happen BEFORE any DB.
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "x", "template_key": "definitely-not-a-template"},
    )
    assert r.status_code == 422


def test_build_template_key_optional(monkeypatch):
    seen = {}
    async def fake_create(email, seed, description, template_key=None):
        seen["template_key"] = template_key
        return ("t", "s")
    monkeypatch.setattr(rb, "_create_and_spawn_build", fake_create)
    r = _client().post(
        "/api/aiuibuilder/build",
        headers={"X-User-Email": "alice@x.com"},
        json={"description": "a todo list"},
    )
    assert r.status_code == 201
    assert seen["template_key"] is None
