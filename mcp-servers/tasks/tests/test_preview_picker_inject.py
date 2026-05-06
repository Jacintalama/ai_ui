"""Picker injection: GET /tasks/preview-app/<slug>/?picker=1 must splice
<script src="/tasks/static/picker.js?v=N"></script> before </head> in served HTML."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os
import shutil
import tempfile

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

import httpx
import main
import pytest
from httpx import ASGITransport


@pytest.fixture
def fake_apps_root(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="aiui-test-picker-")
    try:
        monkeypatch.setattr(main, "_APP_ROOT_FS", tmp)
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _get(url: str):
    transport = ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(url)


async def test_picker_param_injects_script_before_head_close(fake_apps_root):
    slug = "alpha"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    body = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(body)

    resp = await _get(f"/tasks/preview-app/{slug}/?picker=1")
    assert resp.status_code == 200
    text = resp.text
    # Pin the static-mount path AND the version query so a regression
    # in either (e.g. dropping ?v=) trips this test.
    assert '/tasks/static/picker.js?v=1' in text
    pos_script = text.find("/tasks/static/picker.js")
    pos_head_close = text.lower().find("</head>")
    assert 0 < pos_script < pos_head_close


async def test_no_picker_param_serves_unmodified(fake_apps_root):
    slug = "beta"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    body = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(body)

    resp = await _get(f"/tasks/preview-app/{slug}/")
    assert resp.status_code == 200
    assert "/tasks/static/picker.js" not in resp.text


async def test_html_without_head_close_serves_unmodified(fake_apps_root, caplog):
    slug = "gamma"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    # Malformed: no </head>. Common with hand-rolled fragments.
    body = "<!doctype html><body>just a fragment</body>"
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(body)

    with caplog.at_level("WARNING"):
        resp = await _get(f"/tasks/preview-app/{slug}/?picker=1")
    assert resp.status_code == 200
    assert "/tasks/static/picker.js" not in resp.text
    assert any("picker injection skipped" in r.message for r in caplog.records)


async def test_picker_param_on_non_html_serves_unmodified(fake_apps_root):
    slug = "delta"
    app_dir = os.path.join(fake_apps_root, slug)
    os.makedirs(app_dir)
    with open(os.path.join(app_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><head></head><body></body></html>")
    css_body = "body { color: red; }"
    with open(os.path.join(app_dir, "style.css"), "w", encoding="utf-8") as f:
        f.write(css_body)

    resp = await _get(f"/tasks/preview-app/{slug}/style.css?picker=1")
    assert resp.status_code == 200
    assert "/tasks/static/picker.js" not in resp.text
    assert resp.text == css_body
