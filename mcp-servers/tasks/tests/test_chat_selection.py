"""Tests for the /chat endpoint's optional `selection` form field.

Mocks the DB layer entirely (no real Postgres needed on dev machines).
Captures the request sent to the Anthropic API so we can inspect what
the prompt looked like.
"""
from cryptography.fernet import Fernet as _Fernet
import os
os.environ.setdefault("AIUI_FERNET_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from auth import AdminUser, current_admin
from main import app
import routes_tasks


@pytest.fixture
def authed_chat(monkeypatch, tmp_path):
    """Yield a callable that POSTs to /api/tasks/chat with mocked deps.

    Returns (resp, captured) where captured is a dict with keys:
      - "system": the Anthropic system prompt as a string (or empty)
      - "messages": the messages array sent to Anthropic
    """
    SOURCE_ID = uuid4()
    SLUG = "alpha"
    ADMIN_EMAIL = "admin@aiui.local"

    # Stub admin user via dependency override.
    def _admin():
        return AdminUser(email=ADMIN_EMAIL, is_admin=True)
    app.dependency_overrides[current_admin] = _admin

    # Stub _get_owned_task to return a minimal task object with built_app_slug.
    class _FakeTask:
        id = SOURCE_ID
        assignee_email = ADMIN_EMAIL
        built_app_slug = SLUG

    async def _fake_get_owned_task(s, task_id, email):
        return _FakeTask()

    monkeypatch.setattr(routes_tasks, "_get_owned_task", _fake_get_owned_task)

    # Stub the DB session() context manager to a no-op.
    @asynccontextmanager
    async def _fake_session():
        yield MagicMock()
    monkeypatch.setattr(routes_tasks, "session", _fake_session)

    # Point CLAUDE_WORKSPACE at tmp; create the app dir with one file
    # so file_listing has a stable value.
    workspace = tmp_path / "ws"
    app_dir = workspace / "apps" / SLUG
    app_dir.mkdir(parents=True)
    (app_dir / "index.html").write_text("<!doctype html><body>x</body>")
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(workspace))

    # Capture what gets sent to Anthropic. Mock only the anthropic.com call —
    # NOT the ASGI test-client POST (which goes through this same AsyncClient
    # in the route's pipeline). We discriminate on the URL.
    captured = {"system": "", "messages": []}

    class _FakeAnthropicResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"content": [{"type": "text", "text": "ok"}]}

    _real_post = httpx.AsyncClient.post

    async def _fake_post(self, url, *args, **kwargs):
        if "anthropic.com" in str(url):
            body = kwargs.get("json") or {}
            captured["system"] = body.get("system", "")
            captured["messages"] = body.get("messages", [])
            return _FakeAnthropicResponse()
        return await _real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    transport = ASGITransport(app=app)

    async def _do_post(message="hi", selection=None, files=None):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            data = {"source_task_id": str(SOURCE_ID), "message": message}
            if selection is not None:
                data["selection"] = selection
            kwargs = {"data": data}
            if files:
                kwargs["files"] = files
            resp = await c.post(
                "/api/tasks/chat",
                headers={
                    "x-user-email": ADMIN_EMAIL,
                    "x-user-admin": "true",
                },
                **kwargs,
            )
        return resp, captured

    yield _do_post

    app.dependency_overrides.pop(current_admin, None)


def _good_selection():
    return {
        "selector": "main > section.skills > article:nth-of-type(2)",
        "tag": "ARTICLE",
        "attrs": {"class": "skill-card"},
        "outerHtml": "<article class=\"skill-card\"><h3>Frontend</h3></article>",
        "styles": {
            "color": "rgb(34, 34, 34)",
            "backgroundColor": "rgb(255, 255, 255)",
            "padding": "16px",
            "margin": "0 0 12px 0",
            "fontSize": "14px",
            "fontFamily": "Inter, sans-serif",
            "display": "block",
            "borderRadius": "8px",
            "width": "300px",
            "height": "180px"
        },
        "rect": {"x": 120, "y": 240, "w": 300, "h": 180},
        "url": "http://example/preview-app/foo/",
        "pickedAt": 1715000000000
    }


async def test_chat_with_valid_selection_includes_block_in_prompt(authed_chat):
    resp, captured = await authed_chat(
        message="make this blue", selection=json.dumps(_good_selection())
    )
    assert resp.status_code == 200, resp.text
    assert "SELECTED ELEMENT" in captured["system"]
    assert "main > section.skills > article:nth-of-type(2)" in captured["system"]


async def test_chat_with_oversized_selection_returns_400(authed_chat):
    big = json.dumps(_good_selection()) + ("x" * 9000)  # > SELECTION_RAW_MAX
    resp, _ = await authed_chat(message="hi", selection=big)
    assert resp.status_code == 400
    assert "selection" in resp.text.lower()


async def test_chat_with_malformed_selection_json_returns_400(authed_chat):
    resp, _ = await authed_chat(message="hi", selection="{not json")
    assert resp.status_code == 400


async def test_chat_with_invalid_selection_field_returns_400(authed_chat):
    bad = _good_selection()
    bad.pop("selector")  # required field
    resp, _ = await authed_chat(message="hi", selection=json.dumps(bad))
    assert resp.status_code == 400


async def test_chat_without_selection_works_unchanged(authed_chat):
    resp, captured = await authed_chat(message="hi")
    assert resp.status_code == 200, resp.text
    assert "SELECTED ELEMENT" not in captured["system"]


# Tiny PNG bytes (1x1 transparent) — no need for a real image library.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6300010000000500010d0a2db40000"
    "000049454e44ae426082"
)


async def test_chat_with_selection_and_files(authed_chat):
    resp, captured = await authed_chat(
        message="explain this",
        selection=json.dumps(_good_selection()),
        files=[("files", ("a.png", _TINY_PNG, "image/png"))],
    )
    assert resp.status_code == 200, resp.text
    assert "SELECTED ELEMENT" in captured["system"]
    # Image survives — last user message has at least one image content block.
    last = captured["messages"][-1]["content"]
    assert any(part.get("type") == "image" for part in last)
