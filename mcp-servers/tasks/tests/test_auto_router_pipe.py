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
    out, who = await p._agents_first({"messages": _q("hi team")}, "o@example.com")
    assert out == "Ada:\nHello."
    assert "aiui:turns" not in out
    assert who == "Ada", "a named agent has somebody to name"


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
    out, who = await p._agents_first({"messages": _q("hi team")}, "o@example.com")
    assert "aiui:turns" not in out
    assert "Try" in out and "this." in out
    assert who == "Ada"


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
    """Named rather than counted, so re-adding one is a visible failure.

    The second group was withdrawn between 2026-09-10 and 2026-10-29, which
    is six weeks: that is the real clock on a hardcoded free id.
    """
    dead = (
        "openai/gpt-oss-20b:free", "nvidia/nemotron-nano-9b-v2:free",
        "nex-agi/nex-n2.5-mini:free", "nex-agi/nex-n2.5-pro:free",
        "inclusionai/ling-3.0-flash-fin:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    )
    valves = mod.Pipe.Valves()
    for gone in dead:
        assert gone not in mod.FALLBACK_POOL, gone
        for route in ("MODEL_GENERAL", "MODEL_CODER", "MODEL_REASONING"):
            assert getattr(valves, route) != gone, "%s -> %s" % (route, gone)


def test_the_permanently_rate_limited_models_are_not_in_the_pool(mod):
    """A fallback that is always busy is a wasted retry.

    liquid/lfm-2.5-2.6b is the cautionary one. It passed a single arithmetic
    probe in September and was kept, then answered 429 on three of three in
    October, by which time every other id had been withdrawn and it was the
    only candidate left for a general question. One probe is not reliability.
    """
    for busy in ("google/gemma-4-26b-a4b-it:free", "google/gemma-4-31b-it:free",
                 "liquid/lfm-2.5-2.6b:free", "poolside/laguna-s-2.1:free",
                 "poolside/laguna-xs-2.1:free"):
        assert busy not in mod.FALLBACK_POOL, busy


# --- the pool can no longer rot away to nothing (2026-10-29) ----------------
#
# What went wrong: _keep_available only ever SHRINKS the candidate list. Four
# of six ids were withdrawn, which left a general question with exactly one
# candidate, and that one was permanently rate-limited. The chat reported
# "every free model was rate-limited or failed" and nothing said why.


def test_a_gutted_pool_is_topped_up_from_the_catalogue(mod):
    """The failure that was live. Every measured id is gone; the catalogue is
    still serving others, so the person gets an answer instead of an apology."""
    kept = mod._keep_available(["gone-a:free", "gone-b:free"],
                               {"other-x:free", "other-y:free"})
    # _keep_available fails open and hands back the dead list untouched.
    topped = mod._top_up(kept, {"other-x:free", "other-y:free"})
    assert "other-x:free" in topped and "other-y:free" in topped


def test_topping_up_keeps_the_measured_ids_in_front(mod):
    """The probed ids answer; the appended ones are only guesses. Trying a
    guess before a known-good model would make every answer slower."""
    topped = mod._top_up(["measured:free"], {"measured:free", "aaa-guess:free"})
    assert topped[0] == "measured:free", topped


def test_topping_up_never_reaches_for_a_model_that_is_not_a_chat_model(mod):
    """nvidia/nemotron-3.5-content-safety:free is free, live, and would answer
    a question about invoices with a safety verdict."""
    topped = mod._top_up(["a:free"],
                         {"a:free", "nvidia/nemotron-3.5-content-safety:free"})
    assert topped == ["a:free"]


def test_topping_up_never_reaches_for_a_paid_model(mod):
    """The whole promise of this router is that no paid model is ever used,
    and the catalogue it tops up from lists the paid ones too."""
    topped = mod._top_up(["a:free"], {"a:free", "anthropic/expensive-model"})
    assert topped == ["a:free"]


def test_one_message_cannot_try_the_whole_catalogue(mod):
    """Without a cap, a question would spend a minute being refused by ids
    nobody has probed before it gave up."""
    catalogue = {"m%02d:free" % i for i in range(40)}
    assert len(mod._top_up(["a:free"], catalogue)) == mod.MAX_CANDIDATES


def test_an_unreadable_catalogue_adds_nothing(mod):
    """Fails closed in this direction, on purpose: with no catalogue there is
    nothing to top up FROM, and inventing ids would waste the retries."""
    assert mod._top_up(["a:free", "b:free"], set()) == ["a:free", "b:free"]


def test_topping_up_does_not_duplicate_a_candidate(mod):
    """A duplicate is a retry spent asking the same busy model twice."""
    topped = mod._top_up(["a:free"], {"a:free"})
    assert topped == ["a:free"]


def test_every_pool_entry_is_a_free_id(mod):
    """The whole promise of this router is that no paid model is ever used."""
    assert mod.FALLBACK_POOL, "the pool is empty"
    for m in mod.FALLBACK_POOL:
        assert m.endswith(":free"), m
    for name in ("MODEL_GENERAL", "MODEL_CODER", "MODEL_REASONING"):
        assert getattr(mod.Pipe.Valves(), name).endswith(":free"), name


# --- the pipe says what it is doing while the service decides (2026-10-26) --

async def _with_key(mod, monkeypatch, first, who="Mia"):
    """`first` is the reply, `who` the agent that gave it ("" for the
    assistant, which is the free model with tools and is nobody's agent).
    _agents_first returns both since 2026-10-28."""
    p = mod.Pipe()
    p.valves.OPENROUTER_API_KEY = "k"

    async def agents_first(body, email):
        return None if first is None else (first, who)

    monkeypatch.setattr(p, "_agents_first", agents_first)
    return p


async def test_the_pipe_says_who_is_being_chosen_and_who_answered(mod, monkeypatch):
    p = await _with_key(mod, monkeypatch, "**Mia**\n\nOn it.")
    seen = []

    async def emitter(ev):
        seen.append((ev["data"]["description"], ev["data"]["done"]))

    out = await p.pipe({"messages": _q("chase the overdue invoices")},
                       __user__={"email": "o@example.com"}, __event_emitter__=emitter)
    assert out == "**Mia**\n\nOn it."
    # Changed 2026-10-28. "Choosing who answers..." is gone: in the
    # ordinary case nothing is being chosen, and the line made the wait
    # look like a decision. A named agent is still named: that is true.
    assert seen == [("Answered by Mia", True)], seen


async def test_the_assistant_answering_is_not_called_your_agent(mod, monkeypatch):
    """The reported case, 2026-10-28. "hi who is the most richest guy in the
    world" came back under "Answered by your agent" with no agent involved:
    tasks.agent_decision had no row for that chat, and tasks.jev_check showed
    the tool pick returning server:mcp-proxy. So the ASSISTANT answered, which
    is the free model with the tools Jev picked.

    It carries agent=None on its turn, so there is nobody to name, and the
    pipe says nothing at all."""
    p = await _with_key(mod, monkeypatch, "Elon Musk, about $714 billion.", who="")
    seen = []

    async def emitter(ev):
        seen.append((ev["data"]["description"], ev["data"]["done"]))

    out = await p.pipe({"messages": _q("who is the richest guy in the world")},
                       __user__={"email": "o@example.com"}, __event_emitter__=emitter)
    assert out == "Elon Musk, about $714 billion."
    assert seen == [("", True)], seen
    assert not any("agent" in d.lower() for d, _ in seen), seen


async def test_the_status_clears_when_the_free_model_answers_instead(mod, monkeypatch):
    p = await _with_key(mod, monkeypatch, None)
    seen = []

    async def emitter(ev):
        seen.append((ev["data"]["description"], ev["data"]["done"]))

    async def complete(body, headers, category, candidates, emitter):
        return "free model here"

    monkeypatch.setattr(p, "_complete", complete)
    monkeypatch.setattr(mod, "_available_models", lambda key: asyncio.sleep(0, result=set()))
    out = await p.pipe({"messages": _q("chase the overdue invoices")},
                       __user__={"email": "o@example.com"}, __event_emitter__=emitter)
    assert out == "free model here"
    assert seen == [("", True)], seen



async def test_the_web_rendering_with_faces_is_preferred(mod, monkeypatch):
    p = mod.Pipe()

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {
            "turns": [{"agent": {"id": "agent-a", "name": "Ada"}, "answer": "Hello.", "notes": []}],
            "rendered": "**Ada**\n\nHello.",
            "rendered_web": "![Ada](data:image/svg+xml;base64,AAAA) **Ada**\n\nHello.",
            "queue": [], "marker": ""}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    out, who = await p._agents_first({"messages": _q("hi ada")}, "o@example.com")
    assert out.startswith("![Ada](data:image/svg+xml;base64,AAAA) **Ada**")
    assert who == "Ada"


# --- the chat and Open WebUI's background jobs (2026-10-27) ------------------
# Measured on the live site: Open WebUI pops `metadata` off the body before a
# pipe sees it and passes the chat as __chat_id__, so the pipe sent "web" for
# every chat and one person's pin and held question followed them into every
# other chat. And with no task model set, the title, tags and follow-up jobs
# are sent to the chat's own model, here, marked with __task__: they reached
# the agents, so one message ran an agent three times.

def _service(mod, monkeypatch, seen):
    class R:
        status_code = 200
        def json(self): return {
            "turns": [{"agent": {"id": "agent-a", "name": "Ada"}, "answer": "Hi.", "notes": []}],
            "rendered": "**Ada**\n\nHi.", "queue": [], "marker": ""}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            seen.append(json or {}); return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)


async def test_the_chat_open_webui_names_is_the_chat_the_service_hears(mod, monkeypatch):
    p = mod.Pipe()
    p.valves.OPENROUTER_API_KEY = "k"
    seen = []
    _service(mod, monkeypatch, seen)
    out = await p.pipe({"messages": _q("hi ada")}, __user__={"email": "o@example.com"},
                       __chat_id__="chat-123", __metadata__={"chat_id": "chat-123"})
    assert out == "**Ada**\n\nHi."
    assert seen[0]["chat_id"] == "chat-123"


async def test_the_metadata_chat_is_used_when_only_it_is_given(mod, monkeypatch):
    p = mod.Pipe()
    p.valves.OPENROUTER_API_KEY = "k"
    seen = []
    _service(mod, monkeypatch, seen)
    await p.pipe({"messages": _q("hi ada")}, __user__={"email": "o@example.com"},
                 __metadata__={"chat_id": "chat-9"})
    assert seen[0]["chat_id"] == "chat-9"


@pytest.mark.parametrize("task", ["title_generation", "tags_generation",
                                  "follow_up_generation", "query_generation"])
async def test_a_background_job_is_never_sent_to_the_agents(mod, monkeypatch, task):
    p = mod.Pipe()
    p.valves.OPENROUTER_API_KEY = "k"
    seen = []
    _service(mod, monkeypatch, seen)

    async def complete(body, headers, category, candidates, emitter):
        return '{"title": "Coffee shop helpers"}'

    monkeypatch.setattr(p, "_complete", complete)
    monkeypatch.setattr(mod, "_available_models", lambda key: asyncio.sleep(0, result=set()))
    out = await p.pipe({"messages": _q("### Task: make a title\ncreate three assistants")},
                       __user__={"email": "o@example.com"}, __task__=task,
                       __chat_id__="chat-123")
    assert seen == []
    assert out == '{"title": "Coffee shop helpers"}'


async def test_a_background_job_carries_no_route_footer(mod, monkeypatch):
    """The footer is for a person reading a reply. On a title it would be
    part of the title."""
    p = mod.Pipe()
    p.valves.OPENROUTER_API_KEY = "k"

    async def complete(body, headers, category, candidates, emitter):
        return '{"tags": ["coffee"]}' + p._footer("general", "m:free")

    monkeypatch.setattr(p, "_complete", complete)
    monkeypatch.setattr(mod, "_available_models", lambda key: asyncio.sleep(0, result=set()))
    out = await p.pipe({"messages": _q("tags please"), "stream": True},
                       __user__={"email": "o@example.com"}, __task__="tags_generation")
    assert out == '{"tags": ["coffee"]}'
