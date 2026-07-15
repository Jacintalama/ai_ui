import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(monkeypatch):
    import importlib
    import routes_fusion_page
    importlib.reload(routes_fusion_page)
    app = FastAPI()
    app.include_router(routes_fusion_page.router)
    return app, routes_fusion_page


def _hdr(email="user@example.com"):
    return {"X-User-Email": email}


def test_send_requires_identity(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "hi", "preset": "quality"})
    assert r.status_code == 401


def test_send_unknown_preset_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "hi", "preset": "nope"},
               headers=_hdr())
    assert r.status_code == 400


def test_send_appends_user_and_returns_stream_fragment(monkeypatch):
    app, mod = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send",
               data={"message": "what is 2+2?", "preset": "budget"},
               headers=_hdr("a@b.com"))
    assert r.status_code == 200
    body = r.text
    assert 'sse-connect="/tasks/fusion/stream"' in body
    assert 'sse-close="close"' in body
    assert "what is 2+2?" in body
    sess = mod._SESSIONS["a@b.com"]
    assert sess.messages[-1] == {"role": "user", "content": "what is 2+2?"}
    assert sess.preset == "budget"
    assert sess.streaming is True


def test_send_escapes_html_in_message(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send",
               data={"message": "<script>x</script>", "preset": "quality"},
               headers=_hdr("c@d.com"))
    assert "<script>x</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_send_empty_message_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "   ", "preset": "quality"},
               headers=_hdr())
    assert r.status_code == 400


def test_send_while_streaming_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    mod._SESSIONS["e@f.com"] = mod.FusionSession(
        messages=[{"role": "user", "content": "prev"}],
        preset="quality", streaming=True, last_used=time.time())
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "again", "preset": "quality"},
               headers=_hdr("e@f.com"))
    assert r.status_code == 200
    assert "still answering" in r.text.lower()
    # the second message was NOT appended
    assert mod._SESSIONS["e@f.com"].messages == [{"role": "user", "content": "prev"}]


def test_new_clears_session(monkeypatch):
    app, mod = _app(monkeypatch)
    mod._SESSIONS["g@h.com"] = mod.FusionSession(
        messages=[{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "y"}],
        preset="quality", streaming=False, last_used=time.time())
    c = TestClient(app)
    r = c.post("/tasks/fusion/new", headers=_hdr("g@h.com"))
    assert r.status_code == 200
    assert mod._SESSIONS["g@h.com"].messages == []
    assert mod._SESSIONS["g@h.com"].streaming is False


def test_sweep_drops_idle_sessions(monkeypatch):
    _, mod = _app(monkeypatch)
    now = 1000.0
    mod._SESSIONS.clear()
    mod._SESSIONS["old@x.com"] = mod.FusionSession(last_used=now - (3 * 60 * 60))
    mod._SESSIONS["fresh@x.com"] = mod.FusionSession(last_used=now - 60)
    mod._sweep(now=now)
    assert "old@x.com" not in mod._SESSIONS
    assert "fresh@x.com" in mod._SESSIONS


def test_page_route_returns_html(monkeypatch, tmp_path):
    # The page route serves static/fusion.html; assert it is wired even before
    # the file exists by checking the route is registered (404 vs missing route).
    app, _ = _app(monkeypatch)
    routes = {r.path for r in app.routes}
    assert "/tasks/fusion" in routes
