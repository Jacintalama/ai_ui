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
    for s in ("running", "planning", "awaiting_input", "pending"):
        assert rb._public_build_status(s) == "running"


def test_preview_url_shape():
    assert rb._preview_url("todo-a1b2") == (
        "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/"
    )


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
    async def fake_create(email, seed, description):
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
    async def busy(email, seed, description):
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
