"""The Auto (Free) router pipe. The file ships to Open WebUI, not this service,
but its routing rules are pure logic worth testing here, the same way
test_fusion_action.py tests the Fuse action. No key or network is touched."""
import asyncio
import importlib.util
import pathlib

import pytest

PIPE_PATH = (pathlib.Path(__file__).resolve().parents[3]
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
