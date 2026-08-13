"""The Channels page must draw all ten rows before any network call.

CHANNEL_CATALOGUE is a hardcoded tuple, so the list itself was never a query.
link_page() injects the same rows /connections would compute, using an empty
`linked` dict, and the page's script draws from that immediately. These tests
pin: the injected payload exists, covers every platform, carries no per-user
data, and that link_page never touches auth or the database to build it.
"""
import json
import os
import re
from pathlib import Path

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes_gateway as rg

PAGE = Path(__file__).resolve().parents[1] / "static" / "gateway-link.html"
HTML = PAGE.read_text(encoding="utf-8")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(rg.page_router)
    return TestClient(app, raise_server_exceptions=False)


def _extract_channels_payload(html: str) -> list:
    match = re.search(r"window\.__CHANNELS__ = (\[.*?\]);", html)
    assert match, "window.__CHANNELS__ was not injected into the page"
    return json.loads(match.group(1))


def test_link_page_injects_window_channels(client):
    resp = client.get("/tasks/gateway/link")
    assert resp.status_code == 200
    rows = _extract_channels_payload(resp.text)
    platforms = {row["platform"] for row in rows}
    assert platforms == {c["platform"] for c in rg.CHANNEL_CATALOGUE}
    assert len(rows) == 10


def test_the_injected_seed_sits_immediately_before_the_script_tag(client):
    # "Immediately before" is what makes the rows available before the rest
    # of the page's script runs, not merely present somewhere in the file.
    resp = client.get("/tasks/gateway/link")
    body = resp.text
    seed_start = body.find("<script>window.__CHANNELS__")
    assert seed_start != -1
    seed_end = body.index("</script>", seed_start) + len("</script>")
    remainder = body[seed_end:seed_end + 40].lstrip("\n")
    # Nothing but whitespace sits between the seed's own closing tag and the
    # page's original opening <script> tag.
    assert remainder.startswith("<script>"), remainder


def test_injected_payload_carries_no_per_user_data(client):
    # An empty `linked` dict is what _channel_status(entry, {}) is fed, so
    # every row's linked_at must stay null and no name/email can appear.
    resp = client.get("/tasks/gateway/link")
    rows = _extract_channels_payload(resp.text)
    for row in rows:
        assert row.get("linked_at") is None, row
        assert row.get("name") == "", row
        assert row.get("bot") is None, row
    assert "@" not in resp.text.split("window.__CHANNELS__")[1].split(";")[0]


def test_the_escape_neutralizes_a_closing_script_tag(monkeypatch, client):
    # Defense in depth: even though CHANNEL_CATALOGUE is fixed today, prove
    # the escape actually does something, by making one entry's blurb hostile
    # and confirming the raw sequence never reaches the response body.
    hostile = dict(rg.CHANNEL_CATALOGUE[0])
    hostile["blurb"] = "</script><script>alert(1)</script>"
    patched = (hostile,) + rg.CHANNEL_CATALOGUE[1:]
    monkeypatch.setattr(rg, "CHANNEL_CATALOGUE", patched)
    resp = client.get("/tasks/gateway/link")
    assert "</script><script>alert(1)</script>" not in resp.text
    # Only "<" needs escaping: the HTML parser's closing-tag scan matches on
    # a literal "<" immediately followed by "/script", so removing every "<"
    # is what breaks that sequence up, regardless of what follows it.
    assert "\\u003c/script>" in resp.text


def test_link_page_never_opens_a_database_session(monkeypatch, client):
    def _no_db(*args, **kwargs):
        raise AssertionError("link_page must not open a database session")

    monkeypatch.setattr(rg, "session", _no_db)
    resp = client.get("/tasks/gateway/link")
    assert resp.status_code == 200
    rows = _extract_channels_payload(resp.text)
    assert len(rows) == 10


def test_link_page_has_no_current_user_dependency():
    import inspect

    sig = inspect.signature(rg.link_page)
    assert "user" not in sig.parameters
    assert "current_user" not in str(sig)


def test_the_route_still_serves_the_page_without_auth(client):
    # Unrelated to the injection: link_page must stay reachable with no
    # X-User-Email at all, same as before this change.
    resp = client.get("/tasks/gateway/link")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_the_served_page_still_carries_the_copy_other_tests_rely_on(client):
    # Injection must not disturb any of the strings other test files assert
    # on when they read the raw static file directly.
    resp = client.get("/tasks/gateway/link")
    body = resp.text
    for needle in ("Connected as", "Only paste a code", "Use my own bot",
                   "BotFather", "Nobody else can", "Quick connect",
                   "cannot take your own bot yet"):
        assert needle in body, needle
    assert "innerHTML" not in body
    assert "\u2014" not in body and "\u2013" not in body


def test_the_fallback_loading_markup_is_still_in_the_raw_file():
    # If __CHANNELS__ is ever missing (the raw file served some other way),
    # the page must still fall back to today's Loading state instead of
    # breaking, so that markup has to stay in the file untouched.
    assert '<li class="row"><span class="blurb">Loading...</span></li>' in HTML
    assert "if (window.__CHANNELS__)" in HTML


def test_the_page_is_never_cached():
    """A stale copy of this page is indistinguishable from a failed deploy.

    It shipped with no cache directives, so a browser kept its own copy and
    went on rendering the previous channel logos after a deploy replaced every
    one of them. The markup also carries window.__CHANNELS__, computed per
    request from the catalogue and env vars, so a cached copy can claim a
    channel is off when it is live.
    """
    import routes_gateway as rg
    resp = rg.link_page()
    cache = resp.headers.get("cache-control", "")
    assert "no-store" in cache, f"page is cacheable: {cache!r}"
