import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _fake_store(mod, monkeypatch):
    """Swap the chat table for a dict. Without this every send tries to reach a
    real Postgres, which the route swallows, so the tests would quietly measure
    the "database is down" path instead of the one that matters."""
    rows: dict[str, dict] = {}
    seq = {"n": 0}

    async def create(email, title, s):
        seq["n"] += 1
        cid = f"chat-{seq['n']}"
        rows[cid] = {"id": cid, "user_email": email, "title": title,
                     "messages": list(s.messages), "panel": list(s.panel),
                     "judge": s.judge, "preset_label": s.preset_label}
        return cid

    async def save(email, s):
        row = rows.get(s.chat_id or "")
        if row and row["user_email"] == email:
            row.update(messages=list(s.messages), panel=list(s.panel),
                       judge=s.judge, preset_label=s.preset_label)

    async def listing(email):
        return [{"id": r["id"], "title": r["title"]}
                for r in rows.values() if r["user_email"] == email]

    async def load(email, chat_id):
        row = rows.get(chat_id)
        return dict(row) if row and row["user_email"] == email else None

    async def delete(email, chat_id):
        row = rows.get(chat_id)
        if row and row["user_email"] == email:
            del rows[chat_id]

    monkeypatch.setattr(mod, "_create_chat", create)
    monkeypatch.setattr(mod, "_save_chat", save)
    monkeypatch.setattr(mod, "_list_chats", listing)
    monkeypatch.setattr(mod, "_load_chat", load)
    monkeypatch.setattr(mod, "_delete_chat", delete)
    return rows


def _app(monkeypatch):
    import importlib
    import routes_fusion_page
    importlib.reload(routes_fusion_page)
    _fake_store(routes_fusion_page, monkeypatch)
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


def test_send_credits_the_panel_and_the_judge(monkeypatch):
    app, mod = _app(monkeypatch)
    c = TestClient(app)
    _seed(mod, "cr@t.com", [], panel=["gpt-5.5", "claude-opus-4-8"],
          judge="claude-opus-4-8", preset_label="quality", streaming=False)
    r = c.post("/tasks/fusion/send", data={"message": "hi"}, headers=_hdr("cr@t.com"))
    assert r.status_code == 200
    assert ("Answered by GPT-5.5 and Claude Opus 4.8, "
            "combined by Claude Opus 4.8") in r.text


def test_credit_reads_naturally_for_a_sole_panelist(monkeypatch):
    _, mod = _app(monkeypatch)
    s = mod.FusionSession(messages=[], panel=["gpt-5.5"], judge="o3",
                          preset_label="custom", streaming=False, last_used=0.0)
    assert "Answered by GPT-5.5, combined by o3" in mod._credit(s)


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


# ------------------------------------------------------------- chat history

def test_send_creates_a_saved_chat_titled_from_the_first_message(monkeypatch):
    app, mod = _app(monkeypatch)
    rows = _fake_store(mod, monkeypatch)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "what is the weather of ph?"},
               headers=_hdr("h1@t.com"))
    assert r.status_code == 200
    assert r.headers.get("HX-Trigger") == "fusion-chats-changed"
    s = mod._SESSIONS["h1@t.com"]
    assert s.chat_id is not None
    assert rows[s.chat_id]["title"] == "what is the weather of ph?"


def test_second_send_reuses_the_same_chat(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "first"}, headers=_hdr("h2@t.com"))
    first_id = mod._SESSIONS["h2@t.com"].chat_id
    mod._SESSIONS["h2@t.com"].streaming = False
    c.post("/tasks/fusion/send", data={"message": "second"}, headers=_hdr("h2@t.com"))
    assert mod._SESSIONS["h2@t.com"].chat_id == first_id


def test_new_chat_detaches_so_the_next_send_starts_a_fresh_row(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "first"}, headers=_hdr("h3@t.com"))
    first_id = mod._SESSIONS["h3@t.com"].chat_id
    c.post("/tasks/fusion/new", headers=_hdr("h3@t.com"))
    assert mod._SESSIONS["h3@t.com"].chat_id is None
    c.post("/tasks/fusion/send", data={"message": "second"}, headers=_hdr("h3@t.com"))
    assert mod._SESSIONS["h3@t.com"].chat_id != first_id


def test_long_title_is_truncated(monkeypatch):
    _, mod = _app(monkeypatch)
    t = mod._title_from("x" * 200)
    assert len(t) == 48 and t.endswith("…")


def test_title_collapses_whitespace(monkeypatch):
    _, mod = _app(monkeypatch)
    assert mod._title_from("  hello \n  world  ") == "hello world"


def test_open_chat_replays_the_conversation(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "remember me"}, headers=_hdr("h4@t.com"))
    s = mod._SESSIONS["h4@t.com"]
    s.messages.append({"role": "assistant", "content": "**bold** answer"})
    s.streaming = False
    import anyio
    anyio.run(mod._save_chat, "h4@t.com", s)
    cid = s.chat_id
    c.post("/tasks/fusion/new", headers=_hdr("h4@t.com"))
    r = c.get(f"/tasks/fusion/chat/{cid}", headers=_hdr("h4@t.com"))
    assert r.status_code == 200
    assert "remember me" in r.text
    # Replayed answers carry raw markdown for the client's md pass, not SSE.
    assert "**bold** answer" in r.text
    assert 'class="text md"' in r.text
    assert "sse-connect" not in r.text
    assert mod._SESSIONS["h4@t.com"].chat_id == cid


def test_open_chat_rejects_another_users_chat(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "mine"}, headers=_hdr("owner@t.com"))
    cid = mod._SESSIONS["owner@t.com"].chat_id
    r = c.get(f"/tasks/fusion/chat/{cid}", headers=_hdr("thief@t.com"))
    assert r.status_code == 404


def test_delete_removes_the_chat_and_clears_the_open_thread(monkeypatch):
    app, mod = _app(monkeypatch)
    rows = _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "bye"}, headers=_hdr("h5@t.com"))
    cid = mod._SESSIONS["h5@t.com"].chat_id
    r = c.delete(f"/tasks/fusion/chat/{cid}", headers=_hdr("h5@t.com"))
    assert r.status_code == 200
    assert cid not in rows
    assert mod._SESSIONS["h5@t.com"].chat_id is None
    # The deleted chat was on screen, so the thread is cleared out of band.
    assert 'hx-swap-oob="innerHTML"' in r.text


def test_delete_of_another_chat_leaves_the_open_one_alone(monkeypatch):
    app, mod = _app(monkeypatch)
    rows = _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "one"}, headers=_hdr("h6@t.com"))
    old = mod._SESSIONS["h6@t.com"].chat_id
    c.post("/tasks/fusion/new", headers=_hdr("h6@t.com"))
    c.post("/tasks/fusion/send", data={"message": "two"}, headers=_hdr("h6@t.com"))
    current = mod._SESSIONS["h6@t.com"].chat_id
    r = c.delete(f"/tasks/fusion/chat/{old}", headers=_hdr("h6@t.com"))
    assert r.status_code == 200
    assert mod._SESSIONS["h6@t.com"].chat_id == current
    assert 'hx-swap-oob' not in r.text
    assert current in rows


def test_chat_list_shows_titles_and_marks_the_open_one(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "hello there"}, headers=_hdr("h7@t.com"))
    cid = mod._SESSIONS["h7@t.com"].chat_id
    r = c.get("/tasks/fusion/chats", headers=_hdr("h7@t.com"))
    assert r.status_code == 200
    assert "hello there" in r.text
    assert f'hx-get="/tasks/fusion/chat/{cid}"' in r.text
    assert "chatrow active" in r.text


def test_chat_list_is_per_user(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    c.post("/tasks/fusion/send", data={"message": "private"}, headers=_hdr("a1@t.com"))
    r = c.get("/tasks/fusion/chats", headers=_hdr("b1@t.com"))
    assert "private" not in r.text
    assert "No saved chats yet" in r.text


def test_send_survives_a_dead_database(monkeypatch):
    app, mod = _app(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(mod, "_create_chat", boom)
    c = TestClient(app)
    r = c.post("/tasks/fusion/send", data={"message": "still works"},
               headers=_hdr("h8@t.com"))
    assert r.status_code == 200
    assert 'sse-connect="/tasks/fusion/stream"' in r.text
    assert mod._SESSIONS["h8@t.com"].chat_id is None


def test_chat_list_keeps_listening_after_it_swaps_itself(monkeypatch):
    # The list replaces itself via outerHTML, so both the empty and populated
    # renders must carry hx-get/hx-trigger. Without them the first swap leaves
    # an element that never hears fusion-chats-changed again, and new chats only
    # show up on a full reload.
    app, mod = _app(monkeypatch)
    _fake_store(mod, monkeypatch)
    c = TestClient(app)
    empty = c.get("/tasks/fusion/chats", headers=_hdr("l1@t.com")).text
    assert "No saved chats yet" in empty
    for frag in (empty,):
        assert 'hx-get="/tasks/fusion/chats"' in frag
        assert "fusion-chats-changed from:body" in frag
        assert 'hx-swap="outerHTML"' in frag

    c.post("/tasks/fusion/send", data={"message": "now populated"}, headers=_hdr("l1@t.com"))
    full = c.get("/tasks/fusion/chats", headers=_hdr("l1@t.com")).text
    assert "now populated" in full
    assert 'hx-get="/tasks/fusion/chats"' in full
    assert "fusion-chats-changed from:body" in full
    assert 'hx-swap="outerHTML"' in full
