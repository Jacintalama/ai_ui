"""Liveness probe for the tasks service — used by deploy_orchestrator.sh post-deploy smoke."""
import os
import sys

# Stub env vars required by import-time side effects so the test can run
# without a real DB / Fernet key. Mirrors the pattern in
# test_publish_access_gate.py.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402


def test_healthz_ok():
    from main import app
    # raise_server_exceptions=False so the lifespan's init_db (which would
    # try to connect to the stub DB URL) doesn't bubble out — we only care
    # that the route exists and returns 200.
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
