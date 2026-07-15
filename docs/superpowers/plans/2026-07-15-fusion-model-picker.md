# Fusion Model Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick the panel models and the judge on the Fusion chat page (Quality/Budget presets plus an editable Custom picker), instead of the fixed presets.

**Architecture:** A server-driven HTMX picker. The model selection lives in the per-user in-memory session; small `hx-post` endpoints mutate it and return the re-rendered picker fragment. `fusion_engine.fuse` changes from taking a preset name to taking an explicit panel list and judge id; the route resolves preset-or-custom into panel+judge and the stream calls fuse with them.

**Tech Stack:** Python 3.11, FastAPI, `sse_starlette`, vendored HTMX 2.0.4 (already present), pytest. No new dependencies.

## Global Constraints

Copy verbatim into every task; they bind all tasks.

- **Everything stays under `/tasks/`** (already routed end to end). No `api-gateway` or Caddy change.
- **Only the 10 registry models are selectable.** Panel is **1 to 4 models** (engine hard cap); the UI cannot add a 5th or remove the last chip; the judge must be a registry model. All limits re-validated server-side.
- **Reuse the v1 session/auth/stream wiring.** The turn-claim, `generation` guard, and empty-turn snapshot filter in `fusion_stream` are correct and MUST be preserved unchanged.
- **No em-dashes or en-dashes** anywhere (code, comments, docstrings, HTML copy, commit messages). Use `-`, a comma, or "and"/"so".
- **No AI/Claude attribution** in commit messages (write the message and stop; no `Co-Authored-By`/`Generated with`).
- **Never touch or commit `.env`**, never deploy `mcp-servers/tasks/templates.py`.
- **Tests run from `mcp-servers/tasks/`** with bare imports (`import fusion_engine`, `from auth import current_user`). Run `python -m pytest ...` from there. If `python` is missing use `py -3`.
- **Model ids and their labels (set these exactly):** `gpt-5`->"GPT-5", `gpt-5.5`->"GPT-5.5", `o3`->"o3", `gpt-4o`->"GPT-4o", `gpt-4.1`->"GPT-4.1", `claude-opus-4-8`->"Claude Opus 4.8", `claude-opus-4-5`->"Claude Opus 4.5", `claude-sonnet-5`->"Claude Sonnet 5", `claude-fable-5`->"Claude Fable 5", `claude-haiku-4-5-20251001`->"Claude Haiku 4.5".

---

## File Structure

- **Modify** `mcp-servers/tasks/fusion_engine.py` - add `label` to `ModelSpec`, `available_models()`, change `fuse` signature (Task 1).
- **Modify** `mcp-servers/tasks/tests/test_fusion_engine.py` - update the 3 fuse-call tests, add label tests (Task 1).
- **Modify** `mcp-servers/tasks/routes_fusion_page.py` - session panel/judge/preset_label + send/stream/new updates (Task 2), picker fragment builder + picker endpoints (Task 3).
- **Modify** `mcp-servers/tasks/tests/test_routes_fusion_page.py` - update `_seed` + send/stream tests (Task 2), add picker-endpoint tests (Task 3).
- **Modify** `mcp-servers/tasks/static/fusion.html` - replace the preset toggle with the `#picker` div, drop the preset field + sync JS (Task 4).

---

## Task 1: Engine - model labels, available_models(), explicit fuse signature

**Files:**
- Modify: `mcp-servers/tasks/fusion_engine.py`
- Test: `mcp-servers/tasks/tests/test_fusion_engine.py`

**Interfaces:**
- Consumes: existing `PROVIDER_REGISTRY`, `resolve_preset`, `fan_out`, `build_judge_messages`, `_stream_judge`, `_last_user_question`, `PANEL_MAX_TOKENS`, `FUSION_TIMEOUT_S`.
- Produces: `ModelSpec` with a `label: str` field; `available_models() -> list[dict]` returning `[{"id","label","provider"}, ...]` in registry order; `fuse(messages: list[dict], panel: list[str], judge: str, *, client: httpx.AsyncClient | None = None) -> AsyncIterator[str]` (panel+judge explicit; no preset).

- [ ] **Step 1: Write the failing tests**

Add to `mcp-servers/tasks/tests/test_fusion_engine.py` (append at end):

```python
def test_available_models_all_have_labels():
    models = fe.available_models()
    ids = {m["id"] for m in models}
    assert ids == set(fe.PROVIDER_REGISTRY.keys())
    for m in models:
        assert m["label"].strip()
        assert m["provider"] in ("openai", "anthropic")
    by = {m["id"]: m for m in models}
    assert by["gpt-5.5"]["label"] == "GPT-5.5"
    assert by["claude-opus-4-8"]["label"] == "Claude Opus 4.8"
    assert by["claude-haiku-4-5-20251001"]["label"] == "Claude Haiku 4.5"
```

And REPLACE the three existing tests that call `fe.fuse(..., "budget")` / `fe.fuse(..., "quality")` with the explicit-panel/judge form:

```python
@pytest.mark.asyncio
async def test_fuse_all_panel_failed_yields_error(monkeypatch):
    async def all_fail(messages, panel, *, max_tokens, timeout_s, client):
        return [fe.PanelAnswer(m, False, error="x") for m in panel]
    monkeypatch.setattr(fe, "fan_out", all_fail)
    out = "".join([c async for c in fe.fuse(
        [{"role": "user", "content": "q"}],
        ["gpt-4o", "claude-haiku-4-5-20251001"], "gpt-4o")])
    assert "could not" in out.lower() or "unavailable" in out.lower()


@pytest.mark.asyncio
async def test_fuse_judge_fails_falls_back_to_panel_answer(monkeypatch):
    async def two_ok(messages, panel, *, max_tokens, timeout_s, client):
        return [fe.PanelAnswer("gpt-4o", True, "short"),
                fe.PanelAnswer("claude-haiku-4-5-20251001", True, "a much longer better answer")]
    async def judge_boom(judge_id, judge_messages, *, client):
        raise RuntimeError("judge down")
        yield  # pragma: no cover
    monkeypatch.setattr(fe, "fan_out", two_ok)
    monkeypatch.setattr(fe, "_stream_judge", judge_boom)
    out = "".join([c async for c in fe.fuse(
        [{"role": "user", "content": "q"}],
        ["gpt-4o", "claude-haiku-4-5-20251001"], "gpt-4o")])
    assert "a much longer better answer" in out and "judge unavailable" in out.lower()


@pytest.mark.asyncio
async def test_fuse_streams_judge_output_in_order(monkeypatch):
    async def two_ok(messages, panel, *, max_tokens, timeout_s, client):
        return [fe.PanelAnswer("gpt-4o", True, "A"), fe.PanelAnswer("claude-haiku-4-5-20251001", True, "B")]
    async def judge_stream(judge_id, judge_messages, *, client):
        for piece in ["Final ", "synthesized ", "answer."]:
            yield piece
    monkeypatch.setattr(fe, "fan_out", two_ok)
    monkeypatch.setattr(fe, "_stream_judge", judge_stream)
    chunks = [c async for c in fe.fuse(
        [{"role": "user", "content": "q"}],
        ["gpt-4o", "claude-haiku-4-5-20251001"], "gpt-4o")]
    assert "".join(chunks).endswith("Final synthesized answer.")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_fusion_engine.py -q`
Expected: FAIL - `available_models` missing (AttributeError) and `fuse()` got unexpected positional args / TypeError.

- [ ] **Step 3: Add the label field and available_models()**

In `mcp-servers/tasks/fusion_engine.py`, add `label` to `ModelSpec`:

```python
@dataclass(frozen=True)
class ModelSpec:
    provider: str   # "openai" | "anthropic"
    api_model: str
    contract: str   # "openai_new" | "openai_legacy" | "anthropic"
    label: str      # human-facing name for the picker UI
```

Set the label (4th positional arg) on every registry entry:

```python
PROVIDER_REGISTRY: dict[str, ModelSpec] = {
    "gpt-5": ModelSpec("openai", "gpt-5", "openai_new", "GPT-5"),
    "gpt-5.5": ModelSpec("openai", "gpt-5.5", "openai_new", "GPT-5.5"),
    "o3": ModelSpec("openai", "o3", "openai_new", "o3"),
    "gpt-4o": ModelSpec("openai", "gpt-4o", "openai_legacy", "GPT-4o"),
    "gpt-4.1": ModelSpec("openai", "gpt-4.1", "openai_legacy", "GPT-4.1"),
    "claude-opus-4-8": ModelSpec("anthropic", "claude-opus-4-8", "anthropic", "Claude Opus 4.8"),
    "claude-opus-4-5": ModelSpec("anthropic", "claude-opus-4-5", "anthropic", "Claude Opus 4.5"),
    "claude-sonnet-5": ModelSpec("anthropic", "claude-sonnet-5", "anthropic", "Claude Sonnet 5"),
    "claude-fable-5": ModelSpec("anthropic", "claude-fable-5", "anthropic", "Claude Fable 5"),
    "claude-haiku-4-5-20251001": ModelSpec("anthropic", "claude-haiku-4-5-20251001", "anthropic", "Claude Haiku 4.5"),
}
```

Add `available_models()` right after `resolve_preset`:

```python
def available_models() -> list[dict]:
    """Registry models for the picker UI: id, human label, provider. Returned
    in stable registry order (OpenAI first, then Anthropic)."""
    return [{"id": mid, "label": spec.label, "provider": spec.provider}
            for mid, spec in PROVIDER_REGISTRY.items()]
```

- [ ] **Step 4: Change the fuse signature to explicit panel + judge**

Replace the `fuse` function's header and its preset resolution. The current body starts with `panel, judge = resolve_preset(preset)`; change the signature to accept them directly and delete that line:

```python
async def fuse(messages: list[dict], panel: list[str], judge: str, *,
               client: httpx.AsyncClient | None = None) -> AsyncIterator[str]:
    owns = client is None
    client = client or httpx.AsyncClient()
    try:
        answers = await fan_out(messages, panel, max_tokens=PANEL_MAX_TOKENS,
                                timeout_s=FUSION_TIMEOUT_S, client=client)
        ok = [a for a in answers if a.ok and a.text.strip()]
        if not ok:
            yield ("Fusion could not get a response from any panel model right now. "
                   "Please try again, or use a single model.")
            return
        question = _last_user_question(messages)
        judge_messages = build_judge_messages(question, ok)
        try:
            async for chunk in _stream_judge(judge, judge_messages, client=client):
                yield chunk
        except Exception as exc:  # noqa: BLE001 - judge failure falls back to best panel answer
            logger.warning("fusion judge %s failed: %s", judge, exc)
            best = max(ok, key=lambda a: len(a.text))
            yield best.text
            yield "\n\n(fusion judge unavailable; showing the strongest single answer)"
    finally:
        if owns:
            await client.aclose()
```

(`resolve_preset` stays; only `fuse` stops calling it.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_fusion_engine.py -q`
Expected: PASS (all engine tests, including the 3 rewritten fuse tests and the new label test).

- [ ] **Step 6: Dash-scan and commit**

Run: `cd mcp-servers/tasks && grep -nP "[\x{2013}\x{2014}]" fusion_engine.py tests/test_fusion_engine.py`
Expected: no output.

```bash
git add mcp-servers/tasks/fusion_engine.py mcp-servers/tasks/tests/test_fusion_engine.py
git commit -m "feat(fusion): model labels, available_models, explicit panel/judge in fuse"
```

---

## Task 2: Session model - panel/judge/preset_label and route wiring

**Files:**
- Modify: `mcp-servers/tasks/routes_fusion_page.py`
- Test: `mcp-servers/tasks/tests/test_routes_fusion_page.py`

**Interfaces:**
- Consumes: `fusion_engine.resolve_preset`, `fusion_engine.fuse(messages, panel, judge, *, client=None)` (Task 1).
- Produces: `FusionSession` with `panel: list[str]`, `judge: str`, `preset_label: str` (no more `preset`); `_get_session` unchanged; `fusion_send` takes only `message`; `fusion_stream` calls `fuse(snapshot, s.panel, s.judge)`; `fusion_new` keeps the model selection. Module-level `_DEFAULT_PANEL: list[str]`, `_DEFAULT_JUDGE: str` from the quality preset.

- [ ] **Step 1: Update the test file's `_seed` helper and send/stream tests to the new session shape**

In `mcp-servers/tasks/tests/test_routes_fusion_page.py`:

Replace the `_seed` helper so it seeds panel/judge instead of preset:

```python
def _seed(mod, email, messages, panel=None, judge=None, preset_label="custom",
          streaming=True):
    mod._SESSIONS[email] = mod.FusionSession(
        messages=list(messages),
        panel=list(panel or ["gpt-4o", "claude-haiku-4-5-20251001"]),
        judge=judge or "gpt-4o", preset_label=preset_label,
        streaming=streaming, last_used=time.time())
```

Replace `test_send_appends_user_and_returns_stream_fragment`, `test_send_escapes_html_in_message`, `test_send_empty_message_400`, `test_send_while_streaming_is_rejected` (they must no longer pass a `preset` form field), and DELETE `test_send_unknown_preset_400` (there is no preset field anymore). Use exactly:

```python
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
```

In every streaming test, the fake fuse signature changes from `(messages, preset, *, client=None)` to `(messages, panel, judge, *, client=None)`. Update all fake-fuse definitions accordingly, e.g.:

```python
    async def fake_fuse(messages, panel, judge, *, client=None):
        ...
```

Apply that signature change to the fakes in `test_stream_relays_fuse_chunks_and_appends_assistant`, `test_stream_escapes_html_chunks`, `test_stream_no_pending_turn_closes_without_calling_fuse`, `test_stream_reconnect_after_turn_does_not_refuse`, `test_new_chat_during_stream_discards_stale_answer`, `test_stream_already_claimed_turn_does_not_fuse`, and `test_stream_snapshot_drops_empty_history_turn`.

Add three new tests:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -q`
Expected: FAIL - `FusionSession` has no `panel`/`judge`/`preset_label`; `fusion_send` still requires/uses `preset`.

- [ ] **Step 3: Update the session model and its defaults**

In `mcp-servers/tasks/routes_fusion_page.py`, add the module-level defaults after the imports (below `router = APIRouter()`):

```python
_DEFAULT_PANEL, _DEFAULT_JUDGE = fusion_engine.resolve_preset("quality")
```

Replace the `FusionSession` `preset` field with panel/judge/preset_label:

```python
@dataclass
class FusionSession:
    messages: list[dict] = field(default_factory=list)
    panel: list[str] = field(default_factory=lambda: list(_DEFAULT_PANEL))
    judge: str = _DEFAULT_JUDGE
    preset_label: str = "quality"
    streaming: bool = False
    last_used: float = field(default_factory=time.time)
    # Bumped whenever the session is reset (New chat). A stream generator
    # captures it at start and refuses to write its result back if the value
    # changed underneath it, so an in-flight turn can never corrupt a session
    # the user has since cleared or restarted.
    generation: int = 0
```

- [ ] **Step 4: Update send to drop the preset field, and stream to pass panel/judge**

Replace `fusion_send` with:

```python
@router.post("/tasks/fusion/send", include_in_schema=False)
async def fusion_send(message: str = Form(...),
                      user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty message")
    s = _get_session(user.email)
    if not s.panel:
        raise HTTPException(status_code=400, detail="pick at least one model")
    if s.streaming:
        return HTMLResponse(
            '<div class="msg system">Still answering the previous turn, '
            'one moment.</div>')
    s.messages.append({"role": "user", "content": text})
    s.streaming = True
    return HTMLResponse(_user_bubble(text) + _assistant_bubble_streaming())
```

In `fusion_stream`'s generator, change the fuse call line from
`async for chunk in fusion_engine.fuse(fuse_messages, s.preset):`
to:

```python
            async for chunk in fusion_engine.fuse(fuse_messages, s.panel, s.judge):
```

`fusion_new` is unchanged (it already only clears messages/streaming and bumps generation; it does not touch panel/judge/preset_label, which is exactly "keep the model selection").

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -q`
Expected: PASS.

- [ ] **Step 6: Dash-scan and commit**

Run: `cd mcp-servers/tasks && grep -nP "[\x{2013}\x{2014}]" routes_fusion_page.py tests/test_routes_fusion_page.py`
Expected: no output.

```bash
git add mcp-servers/tasks/routes_fusion_page.py mcp-servers/tasks/tests/test_routes_fusion_page.py
git commit -m "feat(fusion): session holds panel/judge/preset_label; send and stream use them"
```

---

## Task 3: Picker fragment builder and picker endpoints

**Files:**
- Modify: `mcp-servers/tasks/routes_fusion_page.py`
- Test: `mcp-servers/tasks/tests/test_routes_fusion_page.py`

**Interfaces:**
- Consumes: `fusion_engine.available_models()`, `fusion_engine.PRESETS`, `fusion_engine.PROVIDER_REGISTRY`, `fusion_engine.resolve_preset`, the session fields from Task 2, `_esc`, `_get_session`, `router`.
- Produces: `_render_picker(s: FusionSession) -> str` (a full `<div id="picker">...</div>`); endpoints `GET /tasks/fusion/picker`, `POST /tasks/fusion/preset`, `POST /tasks/fusion/panel/add`, `POST /tasks/fusion/panel/remove`, `POST /tasks/fusion/judge`, each returning the re-rendered picker fragment.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_routes_fusion_page.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -k picker -q`
Expected: FAIL - the picker routes return 404 / `_render_picker` missing.

- [ ] **Step 3: Add the picker fragment builder**

In `mcp-servers/tasks/routes_fusion_page.py`, add after `_empty_thread`:

```python
def _render_picker(s: FusionSession) -> str:
    """The model-picker fragment: preset tabs, panel chips (with remove), an
    Add-model select, and a judge select. Server-rendered; every mutation
    returns this whole fragment (hx-swap outerHTML into #picker)."""
    models = fusion_engine.available_models()
    label_by_id = {m["id"]: m["label"] for m in models}

    # Preset tabs. Quality/Budget switch the selection; Custom is a passive
    # indicator that lights up when the selection was hand-edited.
    tabs = []
    for name in ("quality", "budget"):
        active = " active" if s.preset_label == name else ""
        tabs.append(
            f'<button class="tab{active}" hx-post="/tasks/fusion/preset" '
            f'hx-vals=\'{{"name": "{name}"}}\' hx-target="#picker" '
            f'hx-swap="outerHTML">{name.capitalize()}</button>')
    custom_active = " active" if s.preset_label == "custom" else ""
    tabs.append(f'<span class="tab passive{custom_active}">Custom</span>')

    # Panel chips. The remove button is omitted when only one chip remains.
    chips = []
    can_remove = len(s.panel) > 1
    for mid in s.panel:
        lbl = _esc(label_by_id.get(mid, mid))
        remove = ""
        if can_remove:
            remove = (f'<button class="x" hx-post="/tasks/fusion/panel/remove" '
                      f'hx-vals=\'{{"model": "{_esc(mid)}"}}\' hx-target="#picker" '
                      f'hx-swap="outerHTML" title="remove">&times;</button>')
        chips.append(f'<span class="chip">{lbl}{remove}</span>')

    # Add-model select (only models not already chosen; hidden once panel is full).
    add = ""
    if len(s.panel) < 4:
        opts = ['<option value="" selected disabled>+ Add model</option>']
        for m in models:
            if m["id"] not in s.panel:
                opts.append(f'<option value="{_esc(m["id"])}">{_esc(m["label"])}</option>')
        add = ('<select class="add" hx-post="/tasks/fusion/panel/add" '
               'hx-trigger="change" hx-target="#picker" hx-swap="outerHTML" '
               'name="model">' + "".join(opts) + '</select>')

    # Judge select (all models; current judge selected).
    jopts = []
    for m in models:
        sel = " selected" if m["id"] == s.judge else ""
        jopts.append(f'<option value="{_esc(m["id"])}"{sel}>{_esc(m["label"])}</option>')
    judge = ('<select class="judge" hx-post="/tasks/fusion/judge" '
             'hx-trigger="change" hx-target="#picker" hx-swap="outerHTML" '
             'name="model">' + "".join(jopts) + '</select>')

    return (
        '<div id="picker" class="picker">'
        f'<div class="tabs">{"".join(tabs)}</div>'
        f'<div class="row"><span class="rlabel">Panel</span>{"".join(chips)}{add}</div>'
        f'<div class="row"><span class="rlabel">Fuse with</span>{judge}</div>'
        '</div>'
    )
```

- [ ] **Step 4: Add the picker endpoints**

In `mcp-servers/tasks/routes_fusion_page.py`, add after `fusion_new`:

```python
@router.get("/tasks/fusion/picker", include_in_schema=False)
async def fusion_picker(
        user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    return HTMLResponse(_render_picker(_get_session(user.email)))


@router.post("/tasks/fusion/preset", include_in_schema=False)
async def fusion_preset(name: str = Form(...),
                        user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if name not in fusion_engine.PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown preset: {name}")
    s = _get_session(user.email)
    s.panel, s.judge = fusion_engine.resolve_preset(name)
    s.preset_label = name
    return HTMLResponse(_render_picker(s))


@router.post("/tasks/fusion/panel/add", include_in_schema=False)
async def fusion_panel_add(model: str = Form(...),
                           user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if model not in fusion_engine.PROVIDER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown model: {model}")
    s = _get_session(user.email)
    if model not in s.panel and len(s.panel) < 4:
        s.panel.append(model)
        s.preset_label = "custom"
    return HTMLResponse(_render_picker(s))


@router.post("/tasks/fusion/panel/remove", include_in_schema=False)
async def fusion_panel_remove(model: str = Form(...),
                              user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    s = _get_session(user.email)
    if model in s.panel and len(s.panel) > 1:
        s.panel.remove(model)
        s.preset_label = "custom"
    return HTMLResponse(_render_picker(s))


@router.post("/tasks/fusion/judge", include_in_schema=False)
async def fusion_judge(model: str = Form(...),
                       user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    if model not in fusion_engine.PROVIDER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown model: {model}")
    s = _get_session(user.email)
    s.judge = model
    s.preset_label = "custom"
    return HTMLResponse(_render_picker(s))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_fusion_page.py -q`
Expected: PASS (all picker tests plus the Task 2 tests).

- [ ] **Step 6: Dash-scan and commit**

Run: `cd mcp-servers/tasks && grep -nP "[\x{2013}\x{2014}]" routes_fusion_page.py tests/test_routes_fusion_page.py`
Expected: no output.

```bash
git add mcp-servers/tasks/routes_fusion_page.py mcp-servers/tasks/tests/test_routes_fusion_page.py
git commit -m "feat(fusion): server-rendered model picker fragment and its edit endpoints"
```

---

## Task 4: Wire the picker into fusion.html

**Files:**
- Modify: `mcp-servers/tasks/static/fusion.html`

**Interfaces:**
- Consumes: `GET /tasks/fusion/picker` (returns the `#picker` fragment) and the picker POST endpoints (Task 3); `POST /tasks/fusion/send` now takes only `message` (Task 2).
- Produces: the page HTML; no Python interface.

- [ ] **Step 1: Remove the old preset toggle, hidden field, and its sync JS**

In `mcp-servers/tasks/static/fusion.html`:

Delete the segmented toggle block in the header (the `<div class="seg"> ... </div>` containing the two `name="preset"` radios and their labels).

Delete the hidden preset input in the composer: the line
`<input type="hidden" name="preset" id="presetField" value="quality" />`.

Delete the JS block that syncs the hidden preset field (the
`document.querySelectorAll('.seg input[name="preset"]')...` listener and its body).

- [ ] **Step 2: Add the picker container above the composer**

Immediately before the `<form class="composer" ...>` element, insert:

```html
  <div id="picker" class="picker" hx-get="/tasks/fusion/picker"
       hx-trigger="load" hx-swap="outerHTML"></div>
```

- [ ] **Step 3: Add picker styles**

In the `<style>` block, replace the now-unused `.seg` rules with picker styles (dark theme, consistent with the page):

```css
    .picker {
      max-width: 820px; width: 100%; margin: 12px auto 0; padding: 0 20px;
      display: flex; flex-direction: column; gap: 10px;
    }
    .picker .tabs { display: inline-flex; gap: 6px; }
    .picker .tab {
      padding: 6px 14px; border-radius: 8px; font-size: 13px; cursor: pointer;
      background: transparent; color: #aeb4c0; border: 1px solid #2a2f3d;
    }
    .picker .tab.active { background: #2b6cff; color: #fff; border-color: #2b6cff; }
    .picker .tab.passive { cursor: default; }
    .picker .row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .picker .rlabel { font-size: 12px; color: #6b7280; min-width: 64px; }
    .picker .chip {
      display: inline-flex; align-items: center; gap: 6px; font-size: 13px;
      padding: 5px 10px; border-radius: 8px; background: #1a1d26; border: 1px solid #262b38;
    }
    .picker .chip .x {
      background: transparent; border: none; color: #8b93a1; cursor: pointer;
      font-size: 15px; line-height: 1; padding: 0;
    }
    .picker .chip .x:hover { color: #fff; }
    .picker select {
      background: #0f1115; color: #e6e8eb; border: 1px solid #2a2f3d;
      border-radius: 8px; padding: 6px 10px; font: inherit; font-size: 13px;
    }
```

- [ ] **Step 4: Confirm the composer no longer sends preset and the page references the picker endpoints**

Run: `cd "/c/All/Work - Code/ai_ui" && grep -n "name=\"preset\"\|presetField\|class=\"seg\"" mcp-servers/tasks/static/fusion.html`
Expected: no output (all preset-toggle remnants gone).
Run: `grep -n "id=\"picker\"\|/tasks/fusion/picker\|hx-post=\"/tasks/fusion/send\"" mcp-servers/tasks/static/fusion.html`
Expected: the picker div with its `hx-get`, and the composer `hx-post` to send.
Run: `grep -nP "[\x{2013}\x{2014}]" mcp-servers/tasks/static/fusion.html`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/fusion.html
git commit -m "feat(fusion): replace the preset toggle with the model picker on the page"
```

---

## Task 5: Final whole-branch review

Controller-run (subagent-driven-development). Dispatch the final reviewer against the full branch diff (`scripts/review-package <merge-base> HEAD`) with the Global Constraints as the attention lens. Priorities:

- The v1 reconnect-safety invariants (turn-claim placeholder before first await, `generation` guard, empty-turn snapshot filter) are still intact after the `fuse` signature change and are exercised by the still-green streaming tests.
- Picker mutations validate against the registry (400 on unknown model/preset), enforce panel 1-4 (no 5th, never remove the last), and always return a well-formed `#picker` fragment. Every model id/label entering HTML passes through `_esc`.
- `hx-vals` JSON in the fragment is valid for every model id (ids contain `.` and `-`, which are fine inside JSON strings).
- No em/en dashes anywhere in the diff; no AI attribution in commits; `fusion_engine` label/`fuse` change is coherent and all engine tests pass; `templates.py` and `.env` untouched.

Fix Critical/Important findings with one fix subagent, re-run the covering tests, re-review, then deploy.

---

## Task 6: Deploy and verify

Controller-run. Same mechanism as the v1 page deploy (no git on server, tar-push changed files, rebuild tasks; never `templates.py`/`.env`).

- [ ] **Step 1: Confirm clean tree and merge to main**

```bash
git status
git checkout main && git merge --ff-only feat/fusion-model-picker
git fetch origin && git log --oneline main..origin/main   # reconcile if origin moved (rebase like last time)
git push origin main
```

- [ ] **Step 2: Push the changed files to the server**

Only these changed under `mcp-servers/tasks/`: `fusion_engine.py`, `routes_fusion_page.py`, `static/fusion.html`. Tar-push them:

```bash
tar -czf - -C mcp-servers/tasks fusion_engine.py routes_fusion_page.py static/fusion.html \
  | ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
    "tar -xzf - -C /root/proxy-server/mcp-servers/tasks"
```

- [ ] **Step 3: Rebuild and recreate tasks**

```bash
ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
  "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 4: Verify**

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" https://ai-ui.coolestdomain.win/tasks/healthz
curl -fsS -o /dev/null -w "picker(no auth) %{http_code}\n" https://ai-ui.coolestdomain.win/tasks/fusion/picker   # expect 401
```

Then signed in to Open WebUI: the Fusion page shows the picker (Quality active, chips Claude Opus 4.8 + GPT-5.5, a Fuse-with dropdown). Switching to Budget refills the chips; adding/removing a model flips the tab to Custom; a real prompt with a custom panel streams one combined answer (logs show each chosen model called plus the judge). Record the deployed SHA in `.superpowers/sdd/progress.md`.

---

## Self-Review (plan author)

- **Spec coverage:** presets + editable Custom (Tasks 3-4), user-picked judge (Task 3 judge endpoint + select), server-driven HTMX picker (Task 3-4), engine label/available_models/fuse-signature (Task 1), session panel/judge/preset_label + send/stream/new (Task 2), 1-4 panel and registry-only validation (Task 3), New chat keeps models (Task 2 `test_new_keeps_model_selection`), out-of-scope items excluded (no reasoning/temperature, no Gemini, no reverse preset-matching). Deploy + verify (Task 6).
- **Placeholder scan:** every code step carries complete code; the only prose steps are deletions in Task 4 (exact strings named) and the controller-run review/deploy tasks.
- **Type/name consistency:** `fuse(messages, panel, judge, *, client=None)` defined in Task 1 and called identically in Task 2's stream and the Task 2 test fakes; `FusionSession.panel/judge/preset_label` defined in Task 2 and read by Task 3's `_render_picker` and endpoints; `_render_picker(s)` returns `<div id="picker">` matching the Task 4 `hx-swap="outerHTML"` target; endpoint paths (`/tasks/fusion/preset`, `/panel/add`, `/panel/remove`, `/judge`, `/picker`) match between the builder's `hx-post`s, the endpoints, and the tests.
