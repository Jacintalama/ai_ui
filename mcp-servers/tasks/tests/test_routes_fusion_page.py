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


def test_send_appends_user_and_returns_stream_fragment(monkeypatch):
    app, mod = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "what is 2+2?"},
               headers=_hdr("a@b.com"))
    assert r.status_code == 200
    body = r.text
    assert 'sse-connect="/tasks/fusion/stream"' in body
    assert 'sse-close="close"' in body
    assert "what is 2+2?" in body
    sess = mod._SESSIONS["a@b.com"]
    assert sess.messages[-1] == {"role": "user", "content": "what is 2+2?"}
    assert sess.streaming is True


def test_send_escapes_html_in_message(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "<script>x</script>"},
               headers=_hdr("c@d.com"))
    assert "<script>x</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_send_empty_message_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "   "}, headers=_hdr())
    assert r.status_code == 400


def test_send_empty_panel_400(monkeypatch):
    app, mod = _app(monkeypatch)
    mod._SESSIONS["nop@t.com"] = mod.FusionSession(
        panel=[], judge="gpt-4o", streaming=False, last_used=time.time())
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "hi"}, headers=_hdr("nop@t.com"))
    assert r.status_code == 400


def test_send_while_streaming_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "e@f.com", [{"role": "user", "content": "prev"}], streaming=True)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "again"}, headers=_hdr("e@f.com"))
    assert r.status_code == 200
    assert "still answering" in r.text.lower()
    assert mod._SESSIONS["e@f.com"].messages == [{"role": "user", "content": "prev"}]


def test_new_clears_session(monkeypatch):
    app, mod = _app(monkeypatch)
    mod._SESSIONS["g@h.com"] = mod.FusionSession(
        messages=[{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "y"}],
        streaming=False, last_used=time.time())
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


def _seed(mod, email, messages, panel=None, judge=None, preset_label="custom",
          streaming=True):
    mod._SESSIONS[email] = mod.FusionSession(
        messages=list(messages),
        panel=list(panel or ["gpt-4o", "claude-haiku-4-5-20251001"]),
        judge=judge or "gpt-4o", preset_label=preset_label,
        streaming=streaming, last_used=time.time())


def test_stream_relays_fuse_chunks_and_appends_assistant(monkeypatch):
    app, mod = _app(monkeypatch)

    async def fake_fuse(messages, panel, judge, *, client=None):
        for piece in ["Final ", "answer."]:
            yield piece
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "s@t.com", [{"role": "user", "content": "q"}], streaming=True)

    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream",
                  headers=_hdr("s@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert "Final " in raw and "answer." in raw
    assert "event: close" in raw
    sess = mod._SESSIONS["s@t.com"]
    assert sess.messages[-1] == {"role": "assistant", "content": "Final answer."}
    assert sess.streaming is False


def test_stream_escapes_html_chunks(monkeypatch):
    app, mod = _app(monkeypatch)

    async def fake_fuse(messages, panel, judge, *, client=None):
        yield "<b>hi</b>"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "esc@t.com", [{"role": "user", "content": "q"}])
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream",
                  headers=_hdr("esc@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert "<b>hi</b>" not in raw
    assert "&lt;b&gt;hi&lt;/b&gt;" in raw


def test_stream_no_pending_turn_closes_without_calling_fuse(monkeypatch):
    app, mod = _app(monkeypatch)
    called = {"fuse": False}

    async def fake_fuse(messages, panel, judge, *, client=None):
        called["fuse"] = True
        yield "should not happen"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    # last message is assistant -> no pending user turn
    _seed(mod, "done@t.com",
          [{"role": "user", "content": "q"},
           {"role": "assistant", "content": "a"}], streaming=False)
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream",
                  headers=_hdr("done@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert called["fuse"] is False
    assert "event: close" in raw


def test_stream_requires_identity(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.get("/tasks/fusion/stream")
    assert r.status_code == 401


def test_stream_reconnect_after_turn_does_not_refuse(monkeypatch):
    # After a turn resolves, an EventSource reconnect on the same session must
    # close without a second (paid) fan-out.
    app, mod = _app(monkeypatch)
    calls = {"n": 0}

    async def fake_fuse(messages, panel, judge, *, client=None):
        calls["n"] += 1
        yield "ans"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "cc@t.com", [{"role": "user", "content": "q"}], streaming=True)
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream", headers=_hdr("cc@t.com")) as r:
        "".join(chunk for chunk in r.iter_text())
    assert calls["n"] == 1
    sess = mod._SESSIONS["cc@t.com"]
    assert sess.messages[-1] == {"role": "assistant", "content": "ans"}
    # simulate the browser EventSource auto-reconnecting on the same turn
    with c.stream("GET", "/tasks/fusion/stream", headers=_hdr("cc@t.com")) as r:
        "".join(chunk for chunk in r.iter_text())
    assert calls["n"] == 1  # NOT re-fused
    assert sess.messages == [{"role": "user", "content": "q"},
                             {"role": "assistant", "content": "ans"}]


def test_new_chat_during_stream_discards_stale_answer(monkeypatch):
    # If the user clicks New chat while a turn is streaming, the in-flight
    # generator's result must be discarded, not appended to the fresh session.
    app, mod = _app(monkeypatch)
    email = "mid@t.com"

    async def fake_fuse(messages, panel, judge, *, client=None):
        s = mod._SESSIONS[email]
        s.messages.clear()
        s.streaming = False
        s.generation += 1  # exactly what fusion_new does
        yield "stale answer"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, email, [{"role": "user", "content": "q"}], streaming=True)
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream", headers=_hdr(email)) as r:
        "".join(chunk for chunk in r.iter_text())
    # the stale answer was discarded; the reset session stays empty
    assert mod._SESSIONS[email].messages == []


def test_new_chat_bumps_generation(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "gen@t.com", [{"role": "user", "content": "q"}], streaming=True)
    g0 = mod._SESSIONS["gen@t.com"].generation
    c = TestClient(app)
    r = c.post("/tasks/fusion/new", headers=_hdr("gen@t.com"))
    assert r.status_code == 200
    sess = mod._SESSIONS["gen@t.com"]
    assert sess.generation == g0 + 1
    assert sess.messages == []


def test_stream_already_claimed_turn_does_not_fuse(monkeypatch):
    # The core of the fix: a session whose last message is an (unfilled)
    # assistant placeholder is a turn already claimed by another generator.
    # A second stream must close without calling fuse.
    app, mod = _app(monkeypatch)
    calls = {"n": 0}

    async def fake_fuse(messages, panel, judge, *, client=None):
        calls["n"] += 1
        yield "x"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "claim@t.com",
          [{"role": "user", "content": "q"},
           {"role": "assistant", "content": ""}], streaming=True)
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream", headers=_hdr("claim@t.com")) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    assert calls["n"] == 0
    assert "event: close" in raw


def test_stream_snapshot_drops_empty_history_turn(monkeypatch):
    # A stray empty assistant turn (from an earlier early-disconnect) must be
    # filtered out of the messages handed to fuse, else Anthropic 400s and the
    # Claude panel silently drops for the rest of the conversation.
    app, mod = _app(monkeypatch)
    seen = {}

    async def fake_fuse(messages, panel, judge, *, client=None):
        seen["messages"] = messages
        yield "ok"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "poison@t.com",
          [{"role": "user", "content": "first"},
           {"role": "assistant", "content": ""},   # stray empty turn
           {"role": "user", "content": "second"}], streaming=True)
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream", headers=_hdr("poison@t.com")) as r:
        "".join(chunk for chunk in r.iter_text())
    # fuse never receives an empty-content message
    assert all((m.get("content") or "").strip() for m in seen["messages"])
    assert {"role": "user", "content": "second"} in seen["messages"]


def test_session_defaults_to_quality(monkeypatch):
    _, mod = _app(monkeypatch)
    s = mod.FusionSession()
    assert s.preset_label == "quality"
    assert s.panel == ["gpt-5.5", "claude-opus-4-8"]
    assert s.judge == "claude-opus-4-8"


def test_stream_calls_fuse_with_session_panel_judge(monkeypatch):
    app, mod = _app(monkeypatch)
    got = {}

    async def fake_fuse(messages, panel, judge, *, client=None):
        got["panel"] = panel
        got["judge"] = judge
        yield "ok"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake_fuse)
    _seed(mod, "pj@t.com", [{"role": "user", "content": "q"}],
          panel=["gpt-5.5", "o3"], judge="claude-opus-4-8")
    c = TestClient(app)
    with c.stream("GET", "/tasks/fusion/stream", headers=_hdr("pj@t.com")) as r:
        "".join(chunk for chunk in r.iter_text())
    assert got["panel"] == ["gpt-5.5", "o3"]
    assert got["judge"] == "claude-opus-4-8"


def test_new_keeps_model_selection(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "keep@t.com",
          [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
          panel=["gpt-5.5", "o3"], judge="o3", preset_label="custom", streaming=False)
    c = TestClient(app)
    r = c.post("/tasks/fusion/new", headers=_hdr("keep@t.com"))
    assert r.status_code == 200
    sess = mod._SESSIONS["keep@t.com"]
    assert sess.messages == []
    assert sess.panel == ["gpt-5.5", "o3"] and sess.judge == "o3"
    assert sess.preset_label == "custom"


def test_picker_get_renders_default_quality(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.get("/tasks/fusion/picker", headers=_hdr("pk@t.com"))
    assert r.status_code == 200
    body = r.text
    assert 'id="picker"' in body
    assert "Claude Opus 4.8" in body and "GPT-5.5" in body   # quality panel chips
    assert "/tasks/fusion/panel/add" in body
    assert "/tasks/fusion/judge" in body


def test_picker_preset_switches_and_sets_label(monkeypatch):
    app, mod = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/preset", data={"name": "budget"}, headers=_hdr("pp@t.com"))
    assert r.status_code == 200
    s = mod._SESSIONS["pp@t.com"]
    assert s.panel == ["gpt-4o", "claude-haiku-4-5-20251001"]
    assert s.judge == "gpt-4o" and s.preset_label == "budget"


def test_picker_preset_custom_keeps_panel_and_only_moves_label(monkeypatch):
    app, mod = _app(monkeypatch)
    c = TestClient(app)
    _seed(mod, "pc@t.com", [], panel=["gpt-5.5", "o3"], judge="o3",
          preset_label="quality", streaming=False)
    r = c.post("/tasks/fusion/preset", data={"name": "custom"}, headers=_hdr("pc@t.com"))
    assert r.status_code == 200
    s = mod._SESSIONS["pc@t.com"]
    assert s.panel == ["gpt-5.5", "o3"] and s.judge == "o3"
    assert s.preset_label == "custom"


def test_picker_renders_custom_as_a_live_tab(monkeypatch):
    _, mod = _app(monkeypatch)
    s = mod.FusionSession(messages=[], panel=["gpt-5.5"], judge="o3",
                          preset_label="quality", streaming=False, last_used=0.0)
    html = mod._render_picker(s)
    assert '"name": "custom"' in html
    assert "tab passive" not in html


def test_picker_preset_unknown_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/preset", data={"name": "nope"}, headers=_hdr("pu@t.com"))
    assert r.status_code == 400


def test_picker_add_model_appends_and_flips_custom(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "pa@t.com", [], panel=["gpt-5.5"], judge="gpt-5.5",
          preset_label="quality", streaming=False)
    c = TestClient(app)
    r = c.post("/tasks/fusion/panel/add", data={"model": "o3"}, headers=_hdr("pa@t.com"))
    assert r.status_code == 200
    s = mod._SESSIONS["pa@t.com"]
    assert s.panel == ["gpt-5.5", "o3"] and s.preset_label == "custom"


def test_picker_add_caps_at_four(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "cap@t.com", [],
          panel=["gpt-5.5", "o3", "gpt-4o", "gpt-4.1"], judge="gpt-4o",
          preset_label="custom", streaming=False)
    c = TestClient(app)
    r = c.post("/tasks/fusion/panel/add", data={"model": "claude-opus-4-8"},
               headers=_hdr("cap@t.com"))
    assert r.status_code == 200
    assert mod._SESSIONS["cap@t.com"].panel == ["gpt-5.5", "o3", "gpt-4o", "gpt-4.1"]


def test_picker_add_duplicate_is_noop(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "dup@t.com", [], panel=["gpt-5.5"], judge="gpt-5.5",
          preset_label="quality", streaming=False)
    c = TestClient(app)
    c.post("/tasks/fusion/panel/add", data={"model": "gpt-5.5"}, headers=_hdr("dup@t.com"))
    assert mod._SESSIONS["dup@t.com"].panel == ["gpt-5.5"]


def test_picker_add_unknown_model_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/panel/add", data={"model": "no-such"}, headers=_hdr("ax@t.com"))
    assert r.status_code == 400


def test_picker_remove_drops_but_refuses_last(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "rm@t.com", [], panel=["gpt-5.5", "o3"], judge="gpt-5.5",
          preset_label="custom", streaming=False)
    c = TestClient(app)
    c.post("/tasks/fusion/panel/remove", data={"model": "o3"}, headers=_hdr("rm@t.com"))
    assert mod._SESSIONS["rm@t.com"].panel == ["gpt-5.5"]
    # removing the last one is refused
    c.post("/tasks/fusion/panel/remove", data={"model": "gpt-5.5"}, headers=_hdr("rm@t.com"))
    assert mod._SESSIONS["rm@t.com"].panel == ["gpt-5.5"]


def test_picker_judge_sets_and_flips_custom(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "jg@t.com", [], panel=["gpt-5.5", "claude-opus-4-8"],
          judge="claude-opus-4-8", preset_label="quality", streaming=False)
    c = TestClient(app)
    r = c.post("/tasks/fusion/judge", data={"model": "gpt-5.5"}, headers=_hdr("jg@t.com"))
    assert r.status_code == 200
    s = mod._SESSIONS["jg@t.com"]
    assert s.judge == "gpt-5.5" and s.preset_label == "custom"


def test_picker_judge_unknown_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/judge", data={"model": "no-such"}, headers=_hdr("ju@t.com"))
    assert r.status_code == 400


def test_picker_requires_identity(monkeypatch):
    app, _ = _app(monkeypatch)
    c = TestClient(app)
    assert c.get("/tasks/fusion/picker").status_code == 401
    assert c.post("/tasks/fusion/preset", data={"name": "budget"}).status_code == 401


def test_picker_full_panel_omits_add_select(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "full@t.com", [],
          panel=["gpt-5.5", "o3", "gpt-4o", "gpt-4.1"], judge="gpt-4o",
          preset_label="custom", streaming=False)
    c = TestClient(app)
    r = c.get("/tasks/fusion/picker", headers=_hdr("full@t.com"))
    assert r.status_code == 200
    assert "/tasks/fusion/panel/add" not in r.text  # no Add-model select at 4


def test_picker_sole_chip_has_no_remove_button(monkeypatch):
    app, mod = _app(monkeypatch)
    _seed(mod, "one@t.com", [], panel=["gpt-5.5"], judge="gpt-5.5",
          preset_label="custom", streaming=False)
    c = TestClient(app)
    r = c.get("/tasks/fusion/picker", headers=_hdr("one@t.com"))
    assert r.status_code == 200
    assert "/tasks/fusion/panel/remove" not in r.text  # cannot remove the last chip
