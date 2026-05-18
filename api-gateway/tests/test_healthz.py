"""Liveness probe for api-gateway — used by deploy_orchestrator.sh post-deploy smoke.

The gateway's catch-all proxy_handler matches every path, so /healthz MUST
be registered before it. This test pins that ordering.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402


def test_healthz_ok():
    from main import app
    # raise_server_exceptions=False so the lifespan's DB pool init (which
    # would fail with no DATABASE_URL) doesn't bubble out of the test.
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
