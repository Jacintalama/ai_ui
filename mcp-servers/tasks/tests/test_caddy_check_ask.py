"""Tests for /__caddy/check_ask — the Caddy on-demand TLS gatekeeper."""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models import PublishedApp


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.fixture
def aiui_host(monkeypatch):
    """Pin AIUI_PUBLIC_BASE_URL so _aiui_parent_host() resolves deterministically."""
    monkeypatch.setenv("AIUI_PUBLIC_BASE_URL", "https://ai-ui.test.example")
    return "ai-ui.test.example"


@pytest.fixture
def app_on_disk(tmp_path, monkeypatch):
    """Stage an apps/ root with one real slug ('real-app') and point main at it."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    (apps_root / "real-app").mkdir()
    (apps_root / "real-app" / "index.html").write_text("<html></html>")
    monkeypatch.setattr("main._APP_ROOT_FS", str(apps_root))
    return str(apps_root)


# ---------------------------------------------------------------------------
# Path 1: AIUI parent host — slug must exist on disk
# ---------------------------------------------------------------------------

async def test_aiui_subdomain_with_app_on_disk_returns_ok(
    transport, aiui_host, app_on_disk
):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=real-app.ai-ui.test.example")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reason"] == "aiui-subdomain"


async def test_aiui_subdomain_without_app_on_disk_returns_404(
    transport, aiui_host, app_on_disk
):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=ghost-app.ai-ui.test.example")
    assert r.status_code == 404
    assert "not found on disk" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Slug + host validation
# ---------------------------------------------------------------------------

async def test_invalid_slug_format_rejected(transport, aiui_host, app_on_disk):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=BadSlug!.ai-ui.test.example")
    assert r.status_code == 404


async def test_unrecognized_parent_falls_through_to_db_check(
    db_session, transport, aiui_host, app_on_disk
):
    # db_session is required so conftest TRUNCATEs published_apps before this
    # test runs — the test relies on the DB fallback returning 404 because
    # the table is empty (no row matches the unrelated host's parent).
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/__caddy/check_ask?domain=anything.unrelated-host.example"
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Path 2: Custom domain — must be verified in published_apps
# ---------------------------------------------------------------------------

async def test_verified_custom_domain_returns_ok(
    db_session, transport, aiui_host, app_on_disk
):
    db_session.add(PublishedApp(
        slug="real-app",
        published_by="ralph@example",
        public_host="real-app.user-domain.example",
        custom_domain="user-domain.example",
        custom_domain_verified_at=datetime.now(timezone.utc),
        published_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/__caddy/check_ask?domain=real-app.user-domain.example"
        )
    assert r.status_code == 200
    assert r.json()["reason"] == "verified-custom-domain"


async def test_unverified_custom_domain_rejected(
    db_session, transport, aiui_host, app_on_disk
):
    db_session.add(PublishedApp(
        slug="real-app",
        published_by="ralph@example",
        public_host="real-app.not-yet-verified.example",
        custom_domain="not-yet-verified.example",
        custom_domain_verified_at=None,
        published_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/__caddy/check_ask?domain=real-app.not-yet-verified.example"
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------

async def test_malformed_domain_rejected(transport, aiui_host, app_on_disk):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=ai-ui.test")
    assert r.status_code == 404


async def test_empty_domain_rejected(transport, aiui_host, app_on_disk):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=")
    assert r.status_code == 404


async def test_path_traversal_slug_rejected(transport, aiui_host, app_on_disk):
    """The slug regex must reject path-traversal attempts before
    `os.path.isdir(_APP_ROOT_FS / slug)` is called. A bypass would let
    an attacker probe arbitrary file-system paths and trigger Let's
    Encrypt issuance for unintended hostnames."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__caddy/check_ask?domain=..bad.ai-ui.test.example")
    assert r.status_code == 404
