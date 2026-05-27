"""The /__public/{slug}/ route MUST require a row in tasks.published_apps.

Background: on 2026-04-30 the access gate was dropped so that any slug with
an apps/<slug>/ directory on disk became reachable at the public subdomain
<slug>.ai-ui.coolestdomain.win/. That conflicted with the Publish app UI —
toggling Publish/Unpublish changed the DB row but the public URL stayed up
either way. These tests pin the gate back in place so:

  - Unpublished slug → 404 (even if apps/<slug>/index.html exists on disk).
  - Static assets (CSS/JS) under an unpublished slug → 404 (no leak).
  - /aiui-config.js for an unpublished slug → 404 (no Supabase URL/anon
    key leaks for drafts).

Devs preview unpublished apps via /tasks/preview-app/<slug>/, which is a
separate route and remains unaffected.
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import pytest
from httpx import ASGITransport, AsyncClient

import crypto_utils
from main import app
from models import ProjectSupabase, PublishedApp


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _stage_app_on_disk(tmp_path, slug, *, html="<html></html>", extra_files=None):
    """Create apps/<slug>/index.html (and optional extras) but NO DB row."""
    apps_dir = tmp_path / "apps" / slug
    apps_dir.mkdir(parents=True)
    (apps_dir / "index.html").write_text(html)
    for name, content in (extra_files or {}).items():
        (apps_dir / name).write_text(content)


# ---------------------------------------------------------------------------
# Negative cases: no published_apps row → 404 even if files exist on disk
# ---------------------------------------------------------------------------

async def test_unpublished_index_returns_404(
    db_session, transport, tmp_path, monkeypatch
):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _stage_app_on_disk(
        tmp_path, "alpha",
        html="<html><body>secret draft content</body></html>",
    )
    # NOTE: no PublishedApp row inserted.
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/")
    assert r.status_code == 404
    assert "secret draft content" not in r.text


async def test_unpublished_static_asset_returns_404(
    db_session, transport, tmp_path, monkeypatch
):
    """Even non-HTML assets must 404 — no CSS/JS/image leak via direct path."""
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _stage_app_on_disk(
        tmp_path, "alpha",
        extra_files={"app.css": "body { background: secret-color; }"},
    )
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/app.css")
    assert r.status_code == 404
    assert "secret-color" not in r.text


async def test_unpublished_aiui_config_does_not_leak_supabase(
    db_session, transport, tmp_path, monkeypatch
):
    """/__public/<slug>/aiui-config.js synthesizes Supabase URL+anon_key from
    project_supabase. When the slug isn't published, that synthesis must NOT
    happen — otherwise a draft's Supabase credentials are exposed publicly."""
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _stage_app_on_disk(tmp_path, "alpha")
    db_session.add(ProjectSupabase(
        slug="alpha",
        supabase_url="https://draft-only.supabase.co",
        anon_key_encrypted=crypto_utils.encrypt("eyJsecret-anon-key"),
        configured_by="ralph@aiui.com",
    ))
    # NOTE: no PublishedApp row inserted.
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/aiui-config.js")
    assert r.status_code == 404
    assert "draft-only.supabase.co" not in r.text
    assert "eyJsecret-anon-key" not in r.text


# ---------------------------------------------------------------------------
# Positive case: published row present → 200 (regression guard)
# ---------------------------------------------------------------------------

async def test_published_app_serves_normally(
    db_session, transport, tmp_path, monkeypatch
):
    """Sanity: with a published_apps row, the route still serves content.
    Guards against an over-broad gate that breaks the happy path."""
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _stage_app_on_disk(
        tmp_path, "alpha",
        html="<html><body>live content</body></html>",
    )
    db_session.add(PublishedApp(
        slug="alpha",
        published_by="ralph@aiui.com",
        public_host="alpha.example.com",
    ))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/")
    assert r.status_code == 200
    assert "live content" in r.text
