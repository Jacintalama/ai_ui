import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "s3cret")
    import importlib
    import routes_fusion
    importlib.reload(routes_fusion)
    app = FastAPI()
    app.include_router(routes_fusion.router)
    return app, routes_fusion


def test_complete_rejects_bad_secret(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/api/fusion/complete", headers={"X-Internal-Secret": "wrong"},
               json={"preset": "budget", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 403


def test_complete_streams_fuse(monkeypatch):
    app, rf = _app(monkeypatch)

    async def fake_fuse(messages, preset, *, client=None):
        for piece in ["one ", "two ", "three"]:
            yield piece
    monkeypatch.setattr(rf.fusion_engine, "fuse", fake_fuse)
    c = TestClient(app)
    r = c.post("/api/fusion/complete", headers={"X-Internal-Secret": "s3cret"},
               json={"preset": "quality", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.text == "one two three"


def test_complete_unknown_preset_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/api/fusion/complete", headers={"X-Internal-Secret": "s3cret"},
               json={"preset": "nope", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400


def test_models_lists_presets(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.get("/api/fusion/models", headers={"X-Internal-Secret": "s3cret"})
    assert r.status_code == 200
    body = r.json()
    assert "quality" in body["presets"] and "budget" in body["presets"]
    assert body["presets"]["quality"]["judge"] == "claude-opus-4-8"
