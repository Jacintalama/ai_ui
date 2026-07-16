"""The internal Fusion API the Open WebUI tool calls.

Internal-only by design: it runs a paid fan-out with no user auth in front of
it, so the secret check is the whole security boundary and gets the most
attention here.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SECRET = "test-internal-secret"


def _app(monkeypatch):
    import importlib
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    import routes_fusion
    importlib.reload(routes_fusion)
    app = FastAPI()
    app.include_router(routes_fusion.router)
    return app, routes_fusion


def _hdr(secret=SECRET):
    return {"X-Internal-Secret": secret}


def _body(**over):
    b = {"messages": [{"role": "user", "content": "q"}],
         "panel": ["gpt-5.5"], "judge": "o3"}
    b.update(over)
    return b


def _fake_fuse(mod, monkeypatch, seen=None):
    async def fake(messages, panel, judge, *, client=None):
        if seen is not None:
            seen.update(messages=messages, panel=panel, judge=judge)
        yield "combined answer"
    monkeypatch.setattr(mod.fusion_engine, "fuse", fake)


def test_no_secret_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/complete", json=_body())
    assert r.status_code == 403


def test_wrong_secret_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/complete", json=_body(),
                             headers=_hdr("nope"))
    assert r.status_code == 403


def test_unset_secret_denies_rather_than_opens(monkeypatch):
    # A missing env var must not turn the door into a hole.
    import importlib
    monkeypatch.delenv("INTERNAL_CALLBACK_SECRET", raising=False)
    import routes_fusion
    importlib.reload(routes_fusion)
    app = FastAPI()
    app.include_router(routes_fusion.router)
    r = TestClient(app).post("/api/fusion/complete", json=_body(), headers=_hdr(""))
    assert r.status_code == 403


def test_complete_streams_the_fused_answer(monkeypatch):
    app, mod = _app(monkeypatch)
    seen = {}
    _fake_fuse(mod, monkeypatch, seen)
    r = TestClient(app).post(
        "/api/fusion/complete",
        json=_body(panel=["gpt-5.5", "claude-opus-4-8"], judge="claude-opus-4-8"),
        headers=_hdr())
    assert r.status_code == 200
    assert "combined answer" in r.text
    assert seen["panel"] == ["gpt-5.5", "claude-opus-4-8"]
    assert seen["judge"] == "claude-opus-4-8"


def test_unknown_model_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/complete",
                             json=_body(panel=["not-a-model"]), headers=_hdr())
    assert r.status_code == 400
    assert "not-a-model" in r.text


def test_unknown_judge_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/complete",
                             json=_body(judge="bogus"), headers=_hdr())
    assert r.status_code == 400


def test_empty_panel_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/complete", json=_body(panel=[]),
                             headers=_hdr())
    assert r.status_code == 422


def test_panel_is_capped(monkeypatch):
    # The cap is what stops one call fanning out to the whole registry.
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post(
        "/api/fusion/complete",
        json=_body(panel=["gpt-5.5", "gpt-5", "o3", "gpt-4o", "gpt-4.1"]),
        headers=_hdr())
    assert r.status_code == 422


def test_empty_turns_are_dropped_before_the_fan_out(monkeypatch):
    # Empty content 400s the Anthropic API, which would silently drop every
    # Claude panelist from the fan-out.
    app, mod = _app(monkeypatch)
    seen = {}
    _fake_fuse(mod, monkeypatch, seen)
    r = TestClient(app).post("/api/fusion/complete", json=_body(messages=[
        {"role": "user", "content": "real"},
        {"role": "assistant", "content": "   "},
    ]), headers=_hdr())
    assert r.status_code == 200
    assert seen["messages"] == [{"role": "user", "content": "real"}]


def test_nothing_to_answer_is_rejected(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_fuse(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/complete",
                             json=_body(messages=[{"role": "user", "content": " "}]),
                             headers=_hdr())
    assert r.status_code == 400


def test_web_search_grounds_the_question(monkeypatch):
    app, mod = _app(monkeypatch)
    seen = {}
    _fake_fuse(mod, monkeypatch, seen)

    async def fake_search(query):
        return [{"title": "PAGASA", "url": "https://pagasa.dost.gov.ph",
                 "snippet": "Rain over Luzon."}]
    monkeypatch.setattr(mod.fusion_search, "web_search", fake_search)
    r = TestClient(app).post("/api/fusion/complete", json=_body(web_search=True),
                             headers=_hdr())
    assert r.status_code == 200
    assert "pagasa.dost.gov.ph" in seen["messages"][-1]["content"]


def test_no_search_unless_asked(monkeypatch):
    app, mod = _app(monkeypatch)
    seen = {}
    _fake_fuse(mod, monkeypatch, seen)

    async def boom(query):
        raise AssertionError("must not search when web_search is false")
    monkeypatch.setattr(mod.fusion_search, "web_search", boom)
    r = TestClient(app).post("/api/fusion/complete", json=_body(), headers=_hdr())
    assert r.status_code == 200
    assert seen["messages"] == [{"role": "user", "content": "q"}]


def test_models_lists_the_registry(monkeypatch):
    app, _ = _app(monkeypatch)
    r = TestClient(app).get("/api/fusion/models", headers=_hdr())
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["models"]}
    assert "gpt-5.5" in ids and "claude-opus-4-8" in ids


def test_models_needs_the_secret(monkeypatch):
    app, _ = _app(monkeypatch)
    assert TestClient(app).get("/api/fusion/models").status_code == 403


# ------------------------------------------------- synthesize (the Fuse action)

def _syn(**over):
    b = {"question": "what is 2+2?",
         "answers": [{"model": "gpt-5.5", "content": "4"},
                     {"model": "o4-mini", "content": "five"}],
         "judge": "claude-opus-4-8"}
    b.update(over)
    return b


def _fake_synth(mod, monkeypatch, seen=None):
    async def fake(question, answers, judge, *, client=None):
        if seen is not None:
            seen.update(question=question, answers=answers, judge=judge)
        yield "verified answer"
    monkeypatch.setattr(mod.fusion_engine, "synthesize", fake)


def test_synthesize_needs_the_secret(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_synth(mod, monkeypatch)
    assert TestClient(app).post("/api/fusion/synthesize", json=_syn()).status_code == 403


def test_synthesize_judges_the_answers_it_is_given(monkeypatch):
    # The whole point of the action: no fan-out, the answers already exist and
    # were already paid for.
    app, mod = _app(monkeypatch)
    seen = {}
    _fake_synth(mod, monkeypatch, seen)

    async def no_fanout(*a, **k):
        raise AssertionError("synthesize must never fan out")
        yield
    monkeypatch.setattr(mod.fusion_engine, "fuse", no_fanout)

    r = TestClient(app).post("/api/fusion/synthesize", json=_syn(), headers=_hdr())
    assert r.status_code == 200
    assert "verified answer" in r.text
    assert seen["question"] == "what is 2+2?"
    assert [a["model"] for a in seen["answers"]] == ["gpt-5.5", "o4-mini"]
    assert seen["judge"] == "claude-opus-4-8"


def test_synthesize_rejects_an_unknown_judge(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_synth(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/synthesize", json=_syn(judge="nope"),
                             headers=_hdr())
    assert r.status_code == 400


def test_synthesize_needs_at_least_one_answer(monkeypatch):
    app, mod = _app(monkeypatch)
    _fake_synth(mod, monkeypatch)
    r = TestClient(app).post("/api/fusion/synthesize", json=_syn(answers=[]),
                             headers=_hdr())
    assert r.status_code == 422
