"""Tests for the runtime window-var injection in serve_published_app."""
import os
import uuid
from datetime import datetime

os.environ.setdefault("AIUI_FERNET_KEY", "v3KGZ9ZpQAQ-HeaR_R-nXvI3T8cPOFYYJQHe3VJYJpw=")

import pytest
from httpx import ASGITransport, AsyncClient

import crypto_utils
from main import app
from models import ProjectSupabase, PublishedApp


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _make_published(db_session, slug, html, supabase_url=None, anon_key=None, tmp_path=None):
    """Set up apps/<slug>/index.html on disk and matching DB rows."""
    apps_dir = tmp_path / "apps" / slug
    apps_dir.mkdir(parents=True)
    (apps_dir / "index.html").write_text(html)
    db_session.add(PublishedApp(
        slug=slug, published_by="ralph@aiui.com",
        public_host=f"{slug}.example.com",
    ))
    if supabase_url:
        db_session.add(ProjectSupabase(
            slug=slug, supabase_url=supabase_url,
            anon_key_encrypted=crypto_utils.encrypt(anon_key),
            configured_by="ralph@aiui.com",
        ))


async def test_html_no_supabase_passes_through(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _make_published(db_session, "alpha",
                    "<html><head><title>x</title></head><body>hi</body></html>",
                    tmp_path=tmp_path)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/")
    assert r.status_code == 200
    assert "window.SUPABASE_URL" not in r.text
    assert "<title>x</title>" in r.text


async def test_html_with_supabase_injects_after_head(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    _make_published(db_session, "alpha",
                    "<html><head><title>x</title></head><body>hi</body></html>",
                    supabase_url="https://demo.supabase.co",
                    anon_key="eyJtest.anon.key",
                    tmp_path=tmp_path)
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/")
    assert r.status_code == 200
    body = r.text
    assert 'window.SUPABASE_URL="https://demo.supabase.co"' in body
    assert 'window.SUPABASE_ANON_KEY="eyJtest.anon.key"' in body
    head_idx = body.lower().find("<head>")
    title_idx = body.lower().find("<title>")
    script_idx = body.find("window.SUPABASE_URL")
    assert head_idx < script_idx < title_idx


async def test_non_html_files_not_modified(db_session, transport, tmp_path, monkeypatch):
    monkeypatch.setattr("main._APP_ROOT_FS", str(tmp_path / "apps"))
    apps_dir = tmp_path / "apps" / "alpha"
    apps_dir.mkdir(parents=True)
    (apps_dir / "index.html").write_text("<html></html>")
    (apps_dir / "app.js").write_text("console.log('hi');")
    db_session.add(PublishedApp(slug="alpha", published_by="ralph@aiui.com",
                                public_host="alpha.example.com"))
    db_session.add(ProjectSupabase(
        slug="alpha", supabase_url="https://x.supabase.co",
        anon_key_encrypted=crypto_utils.encrypt("k"),
        configured_by="ralph@aiui.com",
    ))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__public/alpha/app.js")
    assert r.status_code == 200
    assert r.text == "console.log('hi');"
