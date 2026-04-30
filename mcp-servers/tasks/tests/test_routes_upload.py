"""Integration tests for /api/projects/upload."""
import os

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

_ADMIN_HEADERS = {"x-user-email": "ralph@example.com", "x-user-admin": "true"}


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    """Redirect _APP_ROOT_FS to a tmp dir so tests don't write to /workspace."""
    root = tmp_path / "apps"
    root.mkdir()
    monkeypatch.setattr("routes_upload._APP_ROOT_FS", str(root))
    yield str(root)


async def test_upload_rejects_empty(transport, upload_root, db_session):
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r = await c.post("/api/projects/upload", data={"name": "myapp"})
    assert r.status_code == 400
    assert "no files" in r.json()["detail"].lower()


async def test_upload_writes_files_and_creates_task(transport, upload_root, db_session):
    files = [
        ("files", ("index.html", b"<html><body>hi</body></html>", "text/html")),
        ("files", ("style.css", b"body{color:#000;}", "text/css")),
    ]
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r = await c.post("/api/projects/upload", data={"name": "my coffee shop"}, files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "my-coffee-shop"
    assert body["files_written"] == 2
    assert os.path.isfile(os.path.join(upload_root, "my-coffee-shop", "index.html"))
    assert os.path.isfile(os.path.join(upload_root, "my-coffee-shop", "style.css"))


async def test_upload_creates_subdirectories(transport, upload_root, db_session):
    files = [
        ("files", ("src/main.js", b"console.log('hi')", "text/javascript")),
        ("files", ("src/components/Card.js", b"export default {}", "text/javascript")),
    ]
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r = await c.post("/api/projects/upload", data={"name": "nested"}, files=files)
    assert r.status_code == 201
    assert r.json()["files_written"] == 2
    assert os.path.isfile(os.path.join(upload_root, "nested", "src", "main.js"))
    assert os.path.isfile(
        os.path.join(upload_root, "nested", "src", "components", "Card.js")
    )


async def test_upload_skips_dotfiles_silently(transport, upload_root, db_session):
    files = [
        ("files", ("index.html", b"<html></html>", "text/html")),
        ("files", (".git/HEAD", b"ref: refs/heads/main", "text/plain")),
        ("files", ("node_modules/foo/index.js", b"x", "text/javascript")),
    ]
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r = await c.post("/api/projects/upload", data={"name": "skip-test"}, files=files)
    assert r.status_code == 201
    assert r.json()["files_written"] == 1
    assert os.path.isfile(os.path.join(upload_root, "skip-test", "index.html"))
    assert not os.path.exists(os.path.join(upload_root, "skip-test", ".git"))
    assert not os.path.exists(os.path.join(upload_root, "skip-test", "node_modules"))


async def test_upload_rejects_path_traversal(transport, upload_root, db_session):
    files = [("files", ("../../etc/passwd", b"x", "text/plain"))]
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r = await c.post("/api/projects/upload", data={"name": "evil"}, files=files)
    assert r.status_code == 400
    assert "rejected" in r.json()["detail"].lower() or ".." in r.json()["detail"]


async def test_upload_rejects_disallowed_extension(transport, upload_root, db_session):
    files = [("files", ("malware.exe", b"\x00\x01\x02", "application/octet-stream"))]
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r = await c.post("/api/projects/upload", data={"name": "evil2"}, files=files)
    assert r.status_code == 400
    assert "disallowed" in r.json()["detail"].lower()


async def test_upload_409_on_existing_slug(transport, upload_root, db_session):
    files = [("files", ("index.html", b"<html></html>", "text/html"))]
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=_ADMIN_HEADERS
    ) as c:
        r1 = await c.post("/api/projects/upload", data={"name": "dup"}, files=files)
        assert r1.status_code == 201
        r2 = await c.post("/api/projects/upload", data={"name": "dup"}, files=files)
    assert r2.status_code == 409
