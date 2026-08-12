"""The link page must require a signed-in user, and must never accept a code
without one.

Redeeming is the only way a gateway_links row is created, so an unauthenticated
redeem would let anyone claim any pending code.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import routes_gateway


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_gateway.page_router)
    return TestClient(app, raise_server_exceptions=False)


def test_redeem_without_a_signed_in_user_is_401(client):
    resp = client.post("/tasks/gateway/link", json={"code": "ABCD2345"})
    assert resp.status_code == 401


def test_redeem_with_a_blank_code_is_422(client):
    resp = client.post("/tasks/gateway/link", json={"code": ""},
                       headers={"X-User-Email": "someone@example.com"})
    assert resp.status_code == 422


def test_an_absurdly_long_code_is_refused_before_any_work(client):
    # normalize_code scans every character it is given, so an unbounded body
    # would buy an O(n) scan on a public endpoint. The field is capped instead.
    resp = client.post("/tasks/gateway/link", json={"code": "A" * 100_000},
                       headers={"X-User-Email": "someone@example.com"})
    assert resp.status_code == 422


def test_the_page_route_needs_no_auth(client):
    # The HTML itself is inert. Everything it can do requires the header.
    resp = client.get("/tasks/gateway/link")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_the_page_posts_to_the_same_path():
    page = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "gateway-link.html")
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    assert "/tasks/gateway/link" in html
    # Same-origin fetch, so the browser sends the Open WebUI session cookie and
    # api-gateway can turn it into X-User-Email. An absolute URL would break it.
    assert "https://" not in html.split("fetch(")[1].split(")")[0]


def test_the_page_has_no_dash_characters():
    page = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "gateway-link.html")
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    assert "—" not in html and "–" not in html


def test_connections_needs_a_signed_in_user(client):
    assert client.get("/tasks/gateway/connections").status_code == 401


def test_disconnect_needs_a_signed_in_user(client):
    assert client.delete("/tasks/gateway/connections/telegram").status_code == 401


def test_the_page_names_the_linked_account():
    # The only way a user can notice that a code they were talked into pasting
    # linked somebody else's app to their Brain.
    page = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "gateway-link.html")
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    assert "Connected as" in html
    assert "Only paste a code" in html


def test_the_page_builds_rows_without_innerhtml():
    # Names come from a chat platform and are attacker-influenced, so they must
    # never be interpolated into markup.
    page = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "gateway-link.html")
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    assert "innerHTML" not in html


def test_every_channel_is_listed_even_when_it_is_not_ready(monkeypatch):
    # Listing only what works hides the roadmap. A person should be able to see
    # that Signal exists and why it is not here yet.
    monkeypatch.setenv("GATEWAY_TELEGRAM_BOT", "@aiuiteam_bot")
    rows = [routes_gateway._channel_status(e, {})
            for e in routes_gateway.CHANNEL_CATALOGUE]
    assert {r["platform"] for r in rows} >= {
        "telegram", "cli", "slack", "discord", "whatsapp", "signal"}
    for row in rows:
        assert row["status"] in {"connected", "available", "off", "planned"}
        assert row["label"] and row["icon"], row
        # Every row explains itself: what it is, and if it is not usable, why.
        assert row["blurb"], row["platform"]
        if row["status"] in {"planned", "off"}:
            assert row["note"], row["platform"]


def test_a_channel_is_only_offered_when_this_server_is_configured_for_it(monkeypatch):
    # Presence of the config IS the signal, so the page cannot drift from
    # reality the way a hand-maintained list would.
    monkeypatch.delenv("GATEWAY_TELEGRAM_BOT", raising=False)
    monkeypatch.delenv("GATEWAY_CLI_ENABLED", raising=False)
    by_platform = {e["platform"]: routes_gateway._channel_status(e, {})
                   for e in routes_gateway.CHANNEL_CATALOGUE}
    assert by_platform["telegram"]["status"] == "off"
    assert by_platform["cli"]["status"] == "off"

    monkeypatch.setenv("GATEWAY_TELEGRAM_BOT", "@aiuiteam_bot")
    monkeypatch.setenv("GATEWAY_CLI_ENABLED", "1")
    by_platform = {e["platform"]: routes_gateway._channel_status(e, {})
                   for e in routes_gateway.CHANNEL_CATALOGUE}
    assert by_platform["telegram"]["status"] == "available"
    assert by_platform["cli"]["status"] == "available"


def test_a_connected_channel_outranks_its_catalogue_status(monkeypatch):
    monkeypatch.delenv("GATEWAY_TELEGRAM_BOT", raising=False)
    entry = routes_gateway.CHANNEL_CATALOGUE[0]
    row = routes_gateway._channel_status(
        entry, {"telegram": {"name": "Ralph", "linked_at": "2026-08-12T00:00:00"}})
    assert row["status"] == "connected"
    assert row["name"] == "Ralph"
