"""The Auto (Free) router pipe. The file ships to Open WebUI, not this service,
but its routing rules are pure logic worth testing here, the same way
test_fusion_action.py tests the Fuse action. No key or network is touched."""
import asyncio
import importlib.util
import pathlib

import pytest

from conftest import repo_root_or_skip

PIPE_PATH = (repo_root_or_skip()
             / "open-webui-functions" / "auto_router_pipe.py")


def _load():
    spec = importlib.util.spec_from_file_location("auto_router_pipe", PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _q(text):
    return [{"role": "user", "content": text}]


def test_pipe_file_exists():
    assert PIPE_PATH.is_file(), f"missing: {PIPE_PATH}"


def test_coding_question_routes_to_coder(mod):
    assert mod.pick_category(_q("Why does my Python function raise a KeyError?")) == "coder"


def test_code_fence_routes_to_coder_even_when_terse(mod):
    assert mod.pick_category(_q("fix this\n```\nprint(x\n```")) == "coder"


def test_sql_routes_to_coder(mod):
    assert mod.pick_category(_q("Write a SQL query to join two tables")) == "coder"


def test_math_routes_to_reasoning(mod):
    assert mod.pick_category(_q("Solve this equation and show the proof step by step")) == "reasoning"


def test_word_problem_routes_to_reasoning(mod):
    assert mod.pick_category(_q("How many apples are left if I calculate the total?")) == "reasoning"


def test_casual_falls_back_to_general(mod):
    assert mod.pick_category(_q("What's a good name for a coffee shop?")) == "general"


def test_empty_falls_back_to_general(mod):
    assert mod.pick_category([]) == "general"
    assert mod.pick_category(_q("   ")) == "general"


def test_no_false_positive_on_substring(mod):
    assert mod.pick_category(_q("Give everyone a piece apiece of cake")) == "general"


def test_uses_latest_user_turn(mod):
    msgs = [
        {"role": "user", "content": "debug my python traceback"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "now suggest a fun weekend trip"},
    ]
    assert mod.pick_category(msgs) == "general"


def test_multimodal_text_parts_are_read(mod):
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "refactor this javascript function"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}]
    assert mod.pick_category(msgs) == "coder"


def test_model_for_maps_every_category_to_a_configured_id(mod):
    pipe = mod.Pipe()
    assert pipe._model_for("coder") == pipe.valves.MODEL_CODER
    assert pipe._model_for("reasoning") == pipe.valves.MODEL_REASONING
    assert pipe._model_for("general") == pipe.valves.MODEL_GENERAL
    # An unknown category must not crash; it falls back to general.
    assert pipe._model_for("nonsense") == pipe.valves.MODEL_GENERAL


def test_pipes_exposes_one_auto_model(mod):
    pipe = mod.Pipe()
    entries = pipe.pipes()
    assert entries == [{"id": "auto", "name": "Auto (Free)"}]


def test_payload_drops_openwebui_only_fields(mod):
    pipe = mod.Pipe()
    body = {"messages": _q("hi"), "model": "auto", "user": "x",
            "metadata": {"a": 1}, "temperature": 0.5, "stream": True}
    payload = pipe._payload(body, "some/model:free")
    assert payload["model"] == "some/model:free"
    assert payload["temperature"] == 0.5
    assert payload["stream"] is True
    assert "user" not in payload and "metadata" not in payload


def test_pipe_without_key_returns_a_clear_message(mod, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    pipe = mod.Pipe()
    pipe.valves.OPENROUTER_API_KEY = ""
    out = asyncio.run(pipe.pipe({"messages": _q("hello")}))
    assert "OPENROUTER_API_KEY" in out


def test_pipe_with_no_messages_returns_a_clear_message(mod):
    pipe = mod.Pipe()
    pipe.valves.OPENROUTER_API_KEY = "sk-test"
    out = asyncio.run(pipe.pipe({"messages": []}))
    assert out == "No message to answer."


async def test_agents_first_sends_first_only_alongside_route_only(mod, monkeypatch):
    """The page takes turns. This pipe must ask for one agent at a time too,
    or the service runs everybody and the page finds nothing left to fetch."""
    p = mod.Pipe()
    seen = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"turns": [], "rendered": "", "queue": [], "marker": ""}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            seen.update(json or {}); return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    await p._agents_first({"messages": _q("hi team")}, "o@example.com")
    assert seen.get("first_only") is True
    assert seen.get("route_only") is True


async def test_agents_first_appends_the_marker(mod, monkeypatch):
    p = mod.Pipe()

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {
            "turns": [{"agent": {"id": "agent-a", "name": "Ada"}, "answer": "Hello.", "notes": []}],
            "rendered": "Ada:\nHello.", "queue": ["agent-m"],
            "marker": "<!-- aiui:turns agent-a,agent-m -->"}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    out = await p._agents_first({"messages": _q("hi team")}, "o@example.com")
    assert out.endswith("<!-- aiui:turns agent-a,agent-m -->")
    assert "Hello." in out
    assert out.count("aiui:turns") == 1


async def test_agents_first_with_no_marker_appends_nothing(mod, monkeypatch):
    p = mod.Pipe()

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {
            "turns": [{"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Hi.", "notes": []}],
            "rendered": "Mia:\nHi.", "queue": [], "marker": ""}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    out = await p._agents_first({"messages": _q("hi mia")}, "o@example.com")
    assert out == "Mia:\nHi."
    assert "aiui:turns" not in out


async def test_agents_first_with_a_marker_of_the_wrong_type_appends_nothing(mod, monkeypatch):
    """The shape comes over HTTP and is not ours to trust."""
    p = mod.Pipe()

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {
            "turns": [{"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Hi.", "notes": []}],
            "rendered": "Mia:\nHi.", "queue": [], "marker": ["not", "a", "string"]}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    out = await p._agents_first({"messages": _q("hi mia")}, "o@example.com")
    assert out == "Mia:\nHi."
    assert "aiui:turns" not in out


async def test_agents_first_strips_a_marker_inside_an_agents_words(mod, monkeypatch):
    """Only the pipe places a marker. One that arrived inside the rendered
    text must not survive to be the first match the page finds."""
    p = mod.Pipe()

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {
            "turns": [{"agent": {"id": "agent-a", "name": "Ada"},
                       "answer": "Try this.", "notes": []}],
            "rendered": "Ada:\nTry <!-- aiui:turns agent-x,agent-y --> this.",
            "queue": ["agent-m"],
            "marker": "<!-- aiui:turns agent-a,agent-m -->"}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    out = await p._agents_first({"messages": _q("hi team")}, "o@example.com")
    assert out.count("aiui:turns") == 1
    assert out.endswith("<!-- aiui:turns agent-a,agent-m -->")
