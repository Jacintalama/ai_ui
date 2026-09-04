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


# --- Per-upstream read timeouts ------------------------------------------
# An agent turn the web page waits on runs tools and can take minutes. The
# gateway used one 30s client for every backend, so a turn that did a single
# tool round and took 35s returned 502 to the page while tasks kept running
# it to completion. The agent's write tools had already fired; the page was
# told they had not, left the marker in place, and a reload ran the agent a
# second time. Only tasks gets the long read.

def test_the_tasks_upstream_gets_a_read_timeout_long_enough_for_a_turn():
    import main
    t = main.timeout_for("http://tasks:8210")
    assert t.read >= 420.0, (
        "a tasks read timeout shorter than the pipe's own 420s cuts off a "
        "turn the service is still running")


def test_another_upstream_keeps_the_short_read_timeout():
    import main
    t = main.timeout_for("http://open-webui:8080")
    assert t.read == 30.0, (
        "the long read must not leak to every backend: a stuck one would "
        "hold gateway connections open for seven minutes")


def test_connect_stays_short_on_the_tasks_upstream():
    """A backend that will not accept a socket is down, however long its
    work would take. Only the READ budget is generous."""
    import main
    assert main.timeout_for("http://tasks:8210").connect <= 10.0


def test_the_tasks_upstream_is_resolved_from_the_env_not_hardcoded():
    import main
    os_env = __import__("os").environ
    prev = os_env.get("TASKS_URL")
    os_env["TASKS_URL"] = "http://tasks-elsewhere:9999"
    try:
        assert main.timeout_for("http://tasks-elsewhere:9999").read >= 420.0
        assert main.timeout_for("http://tasks:8210").read == 30.0
    finally:
        if prev is None:
            os_env.pop("TASKS_URL", None)
        else:
            os_env["TASKS_URL"] = prev
