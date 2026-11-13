"""The triage sees more of AIUI (Lukas, 2026-11-13): the platform's own
Publish, the skills, and facts said in an ordinary chat.
Design: docs/plans/2026-11-13-triage-sees-more-design.md.
"""
import asyncio

import pytest

import agent_jev
import agent_memory
import app_triage
import main_assistant
import routes_agent_turn as rt


# --- 1. deploy: the platform's own way first --------------------------------------

def test_publish_is_in_the_catalogue_jev_is_asked_about():
    assert "publish" in app_triage.PLATFORM
    ids = app_triage.catalogue_ids()
    assert ids[:len(app_triage.APPS)] == list(app_triage.APPS)
    assert ids[len(app_triage.APPS):] == list(app_triage.PLATFORM)
    _state, questions = agent_jev.apps_request("put my landing page online")
    assert len(questions) == len(ids)
    last = questions[f"a{len(ids) - 1}"]["instructions"]
    assert "Publish" in last and "online" in last


def test_publish_says_where_and_mentions_vercel():
    how = app_triage.PLATFORM["publish"].how
    assert "App Builder" in how and "Publish" in how and "Vercel" in how


def test_pick_apps_returns_platform_ids_too(monkeypatch):
    ids = app_triage.catalogue_ids()
    scores = [0.0] * len(ids)
    scores[ids.index("publish")] = 0.97

    async def ask_many(email, purpose, state, questions, outcome=None):
        got = {q: agent_jev.Answer(choice=None, value=scores[int(q[1:])],
                                   model="m", input_tokens=1)
               for q in questions}
        if outcome:
            outcome(got)
        return got

    monkeypatch.setattr(agent_jev, "ask_many", ask_many)
    assert asyncio.run(agent_jev.pick_apps("a@b.c", "deploy my app")) == [
        ("publish", 0.97)]


def test_a_publish_pick_makes_the_assistant_answer():
    p = app_triage.plan([("publish", 0.97)], set(), [])
    assert [x["id"] for x in p["platform"]] == ["publish"]
    assert p["apps"] == []
    assert app_triage.needs_assistant(p)


def test_the_brief_says_the_platform_does_it_and_no_outside_hosts():
    b = app_triage.brief(app_triage.plan([("publish", 0.97)], set(), []))
    assert app_triage.PLATFORM["publish"].how in b
    assert "straightforward" in b
    assert "do not suggest other hosting" in b.lower()


def test_the_how_line_is_added_when_the_answer_skips_publish():
    p = app_triage.plan([("publish", 0.97)], set(), [])
    out = app_triage.with_buttons("You could use Netlify for that.", p)
    assert out.rstrip().endswith(app_triage.PLATFORM["publish"].how)


def test_the_how_line_is_not_repeated_when_the_answer_says_publish():
    p = app_triage.plan([("publish", 0.97)], set(), [])
    said = "Open it in the App Builder and click Publish."
    assert app_triage.with_buttons(said, p) == said


# --- 2. skills ------------------------------------------------------------------------

POOL = {
    "weekly-review": {"name": "weekly-review", "tools": [],
                      "description": "Review the week: what shipped, what "
                                     "slipped, what is next."},
    "inbox-triage": {"name": "inbox-triage", "tools": ["gmail"],
                     "description": "Sort the inbox into reply, read, archive."},
    "apology-note": {"name": "apology-note", "tools": [],
                     "description": "Write an apology that repairs things."},
}


def test_one_yes_no_per_skill_about_the_message():
    state, questions = agent_jev.message_skills_request(
        "help me review my week", [(n, s["description"]) for n, s in POOL.items()])
    assert list(questions) == ["s0", "s1", "s2"]
    assert "weekly-review" in questions["s0"]["instructions"]
    assert "help me review my week" in state


def test_pick_skills_for_message_keeps_the_sure_ones_best_first(monkeypatch):
    values = {"s0": 0.95, "s1": 0.2, "s2": 0.97}

    async def ask_many(email, purpose, state, questions, outcome=None):
        assert purpose == agent_jev.PURPOSE_SKILL_FOR
        got = {q: agent_jev.Answer(choice=None, value=values[q], model="m",
                                   input_tokens=1) for q in questions}
        if outcome:
            outcome(got)
        return got

    monkeypatch.setattr(agent_jev, "ask_many", ask_many)
    got = asyncio.run(agent_jev.pick_skills_for_message(
        "a@b.c", "x", [(n, s["description"]) for n, s in POOL.items()]))
    assert got == [("apology-note", 0.97), ("weekly-review", 0.95)]


def test_the_skill_cut_is_its_own():
    assert agent_jev.PURPOSE_SKILL_FOR in agent_jev.CUTS


def test_a_skill_in_the_plan_makes_the_assistant_answer():
    p = app_triage.plan([], {"gmail"}, [], skills=[("weekly-review", 0.95)],
                        pool=POOL)
    assert [s["name"] for s in p["skills"]] == ["weekly-review"]
    assert app_triage.needs_assistant(p)


def test_at_most_two_skills():
    p = app_triage.plan([], set(), [], pool=POOL, skills=[
        ("weekly-review", 0.95), ("inbox-triage", 0.94), ("apology-note", 0.93)])
    assert len(p["skills"]) == 2


def test_the_brief_tells_it_to_read_the_skill_and_follow_it():
    b = app_triage.brief(app_triage.plan([], set(), [], pool=POOL,
                                         skills=[("weekly-review", 0.95)]))
    assert "weekly-review" in b and "skills tool" in b
    assert POOL["weekly-review"]["description"] in b


def test_a_skill_that_needs_an_app_not_connected_gets_its_button():
    p = app_triage.plan([], set(), [], pool=POOL, skills=[("inbox-triage", 0.95)])
    out = app_triage.with_buttons("The inbox-triage skill fits.", p)
    assert "#aiui-connect:gmail" in out


def test_a_skill_whose_app_is_connected_gets_no_button():
    p = app_triage.plan([], {"gmail"}, [], pool=POOL, skills=[("inbox-triage", 0.95)])
    assert "#aiui-connect" not in app_triage.with_buttons("Done.", p)


def test_unknown_skills_are_dropped():
    p = app_triage.plan([], set(), [], pool=POOL, skills=[("nope", 0.99)])
    assert p["skills"] == []


# --- the main chat ------------------------------------------------------------------

class _Body:
    user_email = "owner@example.com"
    chat_id = "chat-1"
    route_only = True
    first_only = False
    agent_id = None

    def __init__(self, text, context=None):
        self.messages = list(context or []) + [{"role": "user", "content": text}]


def _gate_open(monkeypatch):
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda agent: True)
    monkeypatch.setattr(rt.agent_decider, "_key", lambda: "test-key")


def test_triage_pick_asks_about_apps_and_skills(monkeypatch):
    import routes_agents
    _gate_open(monkeypatch)

    async def pick_apps(email, text, context=""):
        return [("publish", 0.97)]

    async def pick_skills(email, text, skills, context=""):
        assert [n for n, _d in skills] == list(POOL)
        return [("weekly-review", 0.95)]

    async def pool(email):
        return POOL

    async def connected(email, strict=False):
        return {"gmail"}

    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(rt.agent_jev, "pick_skills_for_message", pick_skills)
    monkeypatch.setattr(routes_agents, "_skill_pool", pool)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    got = asyncio.run(rt._triage_pick(_Body("help me review my week"),
                                      "help me review my week"))
    assert got["picks"] == [("publish", 0.97)]
    assert got["skills"] == [("weekly-review", 0.95)]
    assert got["pool"] is POOL
    assert got["connected"] == {"gmail"}


def test_a_skill_already_named_in_a_reply_is_not_offered_again(monkeypatch):
    import routes_agents
    _gate_open(monkeypatch)

    async def pick_apps(email, text, context=""):
        return []

    async def pick_skills(email, text, skills, context=""):
        return [("weekly-review", 0.95)]

    async def pool(email):
        return POOL

    async def connected(email, strict=False):
        return set()

    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(rt.agent_jev, "pick_skills_for_message", pick_skills)
    monkeypatch.setattr(routes_agents, "_skill_pool", pool)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    before = [{"role": "user", "content": "review my week"},
              {"role": "assistant", "content": "The weekly-review skill fits."}]
    got = asyncio.run(rt._triage_pick(_Body("thanks!", before), "thanks!"))
    assert got["skills"] == []


def test_skills_failing_leaves_the_app_pick_standing(monkeypatch):
    import routes_agents
    _gate_open(monkeypatch)

    async def pick_apps(email, text, context=""):
        return [("publish", 0.97)]

    async def pool(email):
        raise RuntimeError("skills unreadable")

    async def connected(email, strict=False):
        return set()

    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(routes_agents, "_skill_pool", pool)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    got = asyncio.run(rt._triage_pick(_Body("deploy my app"), "deploy my app"))
    assert got["picks"] == [("publish", 0.97)] and got["skills"] == []


def _wire(monkeypatch, answer="Done."):
    seen = {}

    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        seen["graph"], seen["tool_ids"] = graph, tool_ids
        return {"agent": agent, "answer": answer, "notes": []}

    async def graph_block(_email, _text):
        return "GRAPH"

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(rt.agent_progress, "say", lambda line: None)
    return seen


def test_a_skill_gives_the_assistant_the_skills_tool(monkeypatch):
    seen = _wire(monkeypatch, answer="The weekly-review skill fits; here goes.")
    triage = {"picks": [], "connected": set(), "skills": [("weekly-review", 0.95)],
              "pool": POOL}
    out = asyncio.run(rt._assistant_reply(_Body("review my week"),
                                          "review my week", [], picked=[],
                                          triage=triage))
    assert out is not None
    assert "skills" in seen["tool_ids"]
    assert "weekly-review" in seen["graph"]


def test_a_publish_pick_answers_with_the_how_line(monkeypatch):
    seen = _wire(monkeypatch, answer="You can host it anywhere.")
    triage = {"picks": [("publish", 0.97)], "connected": set(), "skills": [],
              "pool": {}}
    out = asyncio.run(rt._assistant_reply(_Body("deploy my app"),
                                          "deploy my app", [], picked=[],
                                          triage=triage))
    assert app_triage.PLATFORM["publish"].how in out["turns"][0]["answer"]
    assert "do not suggest other hosting" in seen["graph"].lower()


# --- 3. memory: facts said in an ordinary chat --------------------------------------

def test_a_free_model_turn_is_reflected_on(monkeypatch):
    seen = {}

    async def resolve(user_email, agent_id):
        seen["agent_id"] = agent_id
        return "tok", [], "ask", {"id": agent_id, "name": "IO"}, []

    async def reflect(user_email, agent, token, user_text, answer):
        seen.update(email=user_email, token=token, text=user_text, answer=answer)

    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    monkeypatch.setattr(rt.agent_memory, "reflect_after_turn", reflect)
    monkeypatch.setattr(rt.agent_memory, "_last_reflect", {})
    text = "Our project codename is Bluebird and the launch is on March 3."

    async def go():
        task = rt._remember_free_turn(_Body(text), text)
        assert task is not None
        await task

    asyncio.run(go())
    assert seen["agent_id"] == main_assistant.ASSISTANT_ID
    assert seen["text"] == text and seen["token"] == "tok"
    assert seen["answer"] == rt.FREE_ANSWER
    assert agent_memory.should_reflect(text, rt.FREE_ANSWER)


@pytest.mark.parametrize("text", ["hi", "thanks!", "what is 2+2?"])
def test_small_or_short_messages_are_not_reflected_on(monkeypatch, text):
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    assert rt._remember_free_turn(_Body(text), text) is None


def test_a_failure_while_remembering_never_reaches_the_chat(monkeypatch):
    async def resolve(user_email, agent_id):
        raise RuntimeError("no token")

    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    text = "Our project codename is Bluebird and the launch is on March 3."

    async def go():
        task = rt._remember_free_turn(_Body(text), text)
        await task                    # must not raise

    asyncio.run(go())


def test_the_free_model_path_schedules_the_reflection(monkeypatch):
    calls = []

    async def agents_for(email):
        return []

    async def no_pin(key):
        return None

    async def nothing(*a, **k):
        return None

    async def jev_release(*a):
        return False

    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_jev_release", jev_release)
    monkeypatch.setattr(rt, "_agents_for", agents_for)
    monkeypatch.setattr(rt, "_read_pin", no_pin)
    monkeypatch.setattr(rt, "_agents_may_take_unnamed", lambda: False)
    monkeypatch.setattr(rt, "_tool_pick", nothing)
    monkeypatch.setattr(rt, "_triage_pick", nothing)
    monkeypatch.setattr(rt, "_assistant_reply", nothing)
    monkeypatch.setattr(rt, "_remember_free_turn",
                        lambda body, text: calls.append(text))
    text = "Our project codename is Bluebird and the launch is on March 3."
    out = asyncio.run(rt._route_chat(_Body(text)))
    assert out["turns"] == []
    assert calls == [text]


# --- the platform's own cut (calibration 2026-11-13) --------------------------------

def test_the_platform_has_its_own_cut(monkeypatch):
    """Measured live: real deploy questions scored Publish 0.66 to 0.83 while
    every message that was not one stayed at 0.21 or below, so the apps'
    0.90 would miss every deploy question. Publish is cut on its own."""
    assert agent_jev.PURPOSE_PLATFORM in agent_jev.CUTS
    ids = app_triage.catalogue_ids()
    scores = [0.0] * len(ids)
    scores[ids.index("publish")] = agent_jev.cut(agent_jev.PURPOSE_PLATFORM) + 0.01
    scores[ids.index("github")] = agent_jev.cut(agent_jev.PURPOSE_APPS) - 0.01

    async def ask_many(email, purpose, state, questions, outcome=None):
        got = {q: agent_jev.Answer(choice=None, value=scores[int(q[1:])],
                                   model="m", input_tokens=1)
               for q in questions}
        if outcome:
            outcome(got)
        return got

    monkeypatch.setattr(agent_jev, "ask_many", ask_many)
    got = asyncio.run(agent_jev.pick_apps("a@b.c", "put my site online"))
    assert [i for i, _s in got] == ["publish"]
