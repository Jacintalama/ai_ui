"""The gateway must route public /tasks/* paths (preview-app, static) to the
Tasks service. Without this they fall through to Open WebUI, whose SPA then
renders "404: Not Found" for built-app preview links.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import Response  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _client_capturing(monkeypatch):
    import main
    captured = {}

    async def fake_forward(request, backend_url, backend_path, extra_headers):
        captured["url"] = backend_url
        captured["path"] = backend_path
        captured["extra_headers"] = extra_headers
        return Response(content=b"ok", status_code=200)

    monkeypatch.setattr(main, "forward_request", fake_forward)
    return TestClient(main.app, raise_server_exceptions=False), captured


def test_tasks_preview_app_routes_to_tasks_service(monkeypatch):
    client, captured = _client_capturing(monkeypatch)
    r = client.get("/tasks/preview-app/chicken-joy-afa6/")
    assert r.status_code == 200
    assert "tasks" in captured["url"]
    assert "open-webui" not in captured["url"]
    # Path is forwarded intact — the tasks service mounts these WITH the /tasks prefix.
    assert captured["path"] == "/tasks/preview-app/chicken-joy-afa6/"


def test_tasks_static_routes_to_tasks_service(monkeypatch):
    client, captured = _client_capturing(monkeypatch)
    r = client.get("/tasks/static/app.css")
    assert r.status_code == 200
    assert "tasks" in captured["url"]


def test_tasks_healthz_routes_to_tasks_root_health(monkeypatch):
    client, captured = _client_capturing(monkeypatch)
    r = client.get("/tasks/healthz")
    assert r.status_code == 200
    assert "tasks" in captured["url"]
    assert captured["path"] == "/healthz"


def test_public_apps_path_routes_to_tasks_service(monkeypatch):
    client, captured = _client_capturing(monkeypatch)
    r = client.get("/apps/alpha/")
    assert r.status_code == 200
    assert "tasks" in captured["url"]
    assert "open-webui" not in captured["url"]
    assert captured["path"] == "/apps/alpha/"


def test_non_tasks_path_still_routes_to_open_webui(monkeypatch):
    """Regression: ordinary paths must still reach Open WebUI."""
    client, captured = _client_capturing(monkeypatch)
    r = client.get("/some/webui/page")
    assert r.status_code == 200
    assert "open-webui" in captured["url"]


def test_api_tasks_still_routes_to_tasks_service(monkeypatch):
    """Regression: the existing /api/tasks route is unaffected."""
    client, captured = _client_capturing(monkeypatch)
    r = client.get("/api/tasks/whatever")
    assert r.status_code == 200
    assert "tasks" in captured["url"]


def test_api_video_jobs_routes_to_tasks_service_with_gateway_headers(monkeypatch):
    """Parity with /api/tasks: /api/video-jobs/* reaches the tasks upstream and
    carries the gateway-injected identity headers, not client-forged ones."""
    client, captured = _client_capturing(monkeypatch)
    # Client forges an identity header; the gateway must not trust it.
    r = client.get(
        "/api/video-jobs/abc123/status",
        headers={"X-User-Email": "attacker@evil.com"},
    )
    assert r.status_code == 200
    # Routed to the tasks service, not Open WebUI.
    assert "tasks" in captured["url"]
    assert "open-webui" not in captured["url"]
    # Path forwarded intact.
    assert captured["path"] == "/api/video-jobs/abc123/status"
    # Gateway injects its own trusted identity headers...
    assert captured["extra_headers"]["X-Gateway-Validated"] == "true"
    assert "X-User-Email" in captured["extra_headers"]
    # ...and the forged client claim never becomes the trusted identity
    # (no valid JWT here, so the gateway's X-User-Email is empty).
    assert captured["extra_headers"]["X-User-Email"] != "attacker@evil.com"
