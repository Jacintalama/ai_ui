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


# ---------------------------------------------------------------------------
# Agents take turns is OFF, and these say so. The feature shipped on
# 2026-09-04 and was rolled back the same night: Open WebUI renders
# message.output, not message.content, so the page never split anything, and
# the marker sat visible in stored chats. Both pipe rows were reverted in the
# database and the repo copies were not, so for twelve days this file pinned
# behaviour that production did not have, and installing either file from git
# would have switched the broken feature back on.
#
# These tests are inverted rather than deleted. Deleting them would leave
# nothing to notice the next re-import, which is the mistake that let the
# drift live. See docs/decisions/2026-09-16-pipes-match-production.md.
# ---------------------------------------------------------------------------


async def test_agents_first_does_not_ask_for_one_agent_at_a_time(mod, monkeypatch):
    """first_only is what made the service answer as one agent and leave the
    rest for the page to fetch. With the page not fetching, sending it would
    silently drop every other agent's reply."""
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
    assert seen.get("route_only") is True
    assert "first_only" not in seen


async def test_agents_first_never_appends_a_marker(mod, monkeypatch):
    """The service still offers a marker, because the turn machinery behind it
    is intact and only the page half was withdrawn. The pipe ignores it: an
    unread marker is a comment sitting in somebody's saved chat forever."""
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
    assert out == "Ada:\nHello."
    assert "aiui:turns" not in out


async def test_a_marker_an_agent_wrote_is_stripped(mod, monkeypatch):
    """The page still parses this shape. Nothing appends one any more, so a
    marker in a stored message could only have come from a model, by accident
    or because somebody asked it to, and acting on it would start a turn flow
    nobody asked for."""
    p = mod.Pipe()

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {
            "turns": [{"agent": {"id": "agent-a", "name": "Ada"},
                       "answer": "Try this.", "notes": []}],
            "rendered": "Ada:\nTry <!-- aiui:turns agent-x,agent-y --> this.",
            "queue": [], "marker": ""}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    out = await p._agents_first({"messages": _q("hi team")}, "o@example.com")
    assert "aiui:turns" not in out
    assert "Try" in out and "this." in out


# ---------------------------------------------------------------------------
# Withdrawn model ids. Measured against the live API on 2026-09-10: the general
# route pointed at openai/gpt-oss-20b:free, which OpenRouter no longer serves,
# and two of the four fallbacks were withdrawn or permanently rate-limited. A
# request for a withdrawn id fails exactly the way a rate limit does, so the
# router spent its whole retry budget on models that could not have answered
# and then reported that every free model was busy.
# ---------------------------------------------------------------------------


def test_a_withdrawn_model_is_dropped_before_it_costs_a_retry(mod):
    pool = ["gone:free", "alive:free"]
    assert mod._keep_available(pool, {"alive:free"}) == ["alive:free"]


def test_the_order_of_the_pool_survives_filtering(mod):
    """The pool is a priority order, fastest first. Filtering must not shuffle
    it, or a slow model gets tried before a fast one."""
    pool = ["first:free", "second:free", "third:free"]
    kept = mod._keep_available(pool, {"third:free", "first:free"})
    assert kept == ["first:free", "third:free"]


def test_an_unreadable_catalogue_leaves_the_pool_alone(mod):
    """Fails open. A router that refuses to try anything because it could not
    read a catalogue is worse than one that tries an id that turns out to be
    gone: the first can never answer, the second usually does."""
    pool = ["a:free", "b:free"]
    assert mod._keep_available(pool, set()) == pool


def test_a_catalogue_matching_nothing_leaves_the_pool_alone(mod):
    """If the catalogue claims not one of our models exists, the catalogue is
    far likelier to be wrong than every provider to have withdrawn at once."""
    pool = ["a:free", "b:free"]
    assert mod._keep_available(pool, {"unrelated:free"}) == pool


def test_the_withdrawn_ids_are_not_in_the_pool(mod):
    """Named rather than counted, so re-adding one is a visible failure."""
    for dead in ("openai/gpt-oss-20b:free", "nvidia/nemotron-nano-9b-v2:free"):
        assert dead not in mod.FALLBACK_POOL, dead
        assert dead != mod.Pipe.Valves().MODEL_GENERAL, dead


def test_the_permanently_rate_limited_model_is_not_in_the_pool(mod):
    """google/gemma-4-26b-a4b-it:free answered 429 on every probe. It is not a
    fallback: a fallback that is always busy is a wasted retry."""
    assert "google/gemma-4-26b-a4b-it:free" not in mod.FALLBACK_POOL


def test_every_pool_entry_is_a_free_id(mod):
    """The whole promise of this router is that no paid model is ever used."""
    assert mod.FALLBACK_POOL, "the pool is empty"
    for m in mod.FALLBACK_POOL:
        assert m.endswith(":free"), m
    for name in ("MODEL_GENERAL", "MODEL_CODER", "MODEL_REASONING"):
        assert getattr(mod.Pipe.Valves(), name).endswith(":free"), name
