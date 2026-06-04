"""GET /tasks/edit/{slug}: token-auth deep link serving the editor in edit mode."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

import httpx
import main
import pytest
from httpx import ASGITransport


async def _get(url: str):
    transport = ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(url)


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(
        main, "_verify_edit_token",
        lambda tok, slug: "u@x.com" if tok == "good" else None)
    return monkeypatch


async def test_valid_token_serves_editor(patched):
    async def _resolve(slug, owner):
        return "task-abc"
    patched.setattr(main, "_resolve_edit_task", _resolve)
    resp = await _get("/tasks/edit/my-app?token=good")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-store"
    assert "__EDIT_CTX__" in resp.text
    assert "task-abc" in resp.text


async def test_bad_token_403(patched):
    resp = await _get("/tasks/edit/my-app?token=bad")
    assert resp.status_code == 403


async def test_not_owner_403(patched):
    async def _resolve(slug, owner):
        return None
    patched.setattr(main, "_resolve_edit_task", _resolve)
    resp = await _get("/tasks/edit/my-app?token=good")
    assert resp.status_code == 403


async def test_invalid_slug_400(patched):
    resp = await _get("/tasks/edit/Bad_Slug!!?token=good")
    assert resp.status_code == 400


async def test_injection_is_json_escaped(patched):
    async def _resolve(slug, owner):
        return "task</script><b>x"
    patched.setattr(main, "_resolve_edit_task", _resolve)
    resp = await _get("/tasks/edit/my-app?token=good")
    # The dangerous value must be escaped, never reflected raw.
    assert "task</script>" not in resp.text
    assert "\\u003c" in resp.text
