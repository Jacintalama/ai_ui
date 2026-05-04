"""Regression: /tasks/preview-app/<slug>/ must serve a project's first
top-level .html file when index.html is missing.

Background: a user uploaded a single 'aiui-design.html' file via the
new-project upload flow. The old upload code wrote a duplicate
'index.html' alias to disk so the preview iframe at /tasks/preview-app/
<slug>/ would resolve. The duplicate showed up in the Files tree as a
phantom file — same content as the source, confusing.

Fix: drop the duplicate-write in routes_upload.py and instead make the
preview-app route fall back to the first .html on disk when index.html
is missing. This test pins that behavior.
"""
import os
import shutil
import tempfile

import httpx
import main
import pytest
from httpx import ASGITransport


@pytest.fixture
def fake_apps_root(monkeypatch):
    """Point _APP_ROOT_FS at a tmp dir we can write into."""
    tmp = tempfile.mkdtemp(prefix="aiui-test-apps-")
    try:
        monkeypatch.setattr(main, "_APP_ROOT_FS", tmp)
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _get(url: str):
    transport = ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(url)


async def test_root_falls_back_to_first_html_when_no_index(fake_apps_root):
    """Project ships a single 'aiui-design.html' (no index.html). A bare
    GET /tasks/preview-app/<slug>/ must return that file's content."""
    slug = "alpha"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    body = "<!doctype html><title>aiui design</title><h1>hi</h1>"
    with open(os.path.join(app_dir, "aiui-design.html"), "w", encoding="utf-8") as f:
        f.write(body)

    r = await _get(f"/tasks/preview-app/{slug}/")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
    assert "aiui design" in r.text
    assert r.headers.get("content-type", "").startswith("text/html")


async def test_root_prefers_index_when_present(fake_apps_root):
    """If index.html exists, it wins — fallback only kicks in when missing."""
    slug = "beta"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>real index</title>")
    with open(os.path.join(app_dir, "other.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>not me</title>")

    r = await _get(f"/tasks/preview-app/{slug}/")
    assert r.status_code == 200
    assert "real index" in r.text
    assert "not me" not in r.text


async def test_404_when_no_html_and_no_index(fake_apps_root):
    """No HTML at all → 404, not server error."""
    slug = "gamma"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    # Only a CSS file — no HTML to fall back to.
    with open(os.path.join(app_dir, "main.css"), "w", encoding="utf-8") as f:
        f.write("body{color:red}")

    r = await _get(f"/tasks/preview-app/{slug}/")
    assert r.status_code == 404


async def test_first_html_alphabetically_wins(fake_apps_root):
    """If multiple non-index HTMLs exist, the alphabetically-first wins —
    deterministic so the user sees the same fallback every visit."""
    slug = "delta"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    with open(os.path.join(app_dir, "z-last.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>z last</title>")
    with open(os.path.join(app_dir, "a-first.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>a first</title>")

    r = await _get(f"/tasks/preview-app/{slug}/")
    assert r.status_code == 200
    assert "a first" in r.text
    assert "z last" not in r.text
