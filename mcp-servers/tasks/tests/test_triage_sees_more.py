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
    pub = questions[f"a{ids.index('publish')}"]["instructions"]
    assert "Publish" in pub and "online" in pub
    ver = questions[f"a{ids.index('vercel')}"]["instructions"]
    assert "Vercel" in ver and "Never a request to build" in ver


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
    monkeypatch.setattr(rt.agent_skills, "load_all", lambda: POOL)
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
    monkeypatch.setattr(rt.agent_skills, "load_all", lambda: POOL)
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

    def pool():
        raise RuntimeError("skills unreadable")

    async def connected(email, strict=False):
        return set()

    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(rt.agent_skills, "load_all", pool)
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

    async def every_tool(email):
        return ["skills", "gmail", "calendar"]

    async def write_pin(key, tools):
        seen["pinned"] = list(tools)

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(rt.agent_progress, "say", lambda line: None)
    monkeypatch.setattr(rt, "_every_tool_for", every_tool)
    monkeypatch.setattr(rt, "_write_tools_pin", write_pin)
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

FACT = "Our project codename is Bluebird and the launch is on March 3."


def _jev_says(monkeypatch, value):
    async def worth(email, user_text, answer):
        return value
    monkeypatch.setattr(agent_jev, "worth_remembering", worth)


def _memory_offline(monkeypatch, seen):
    async def facts(email):
        return []

    async def complete(payload, token, timeout):
        seen["prompt"] = payload["messages"][0]["content"]
        seen["token"] = token
        return {"choices": [{"message": {"content":
                '{"facts": ["Their project codename is Bluebird."], "notes": ["n"]}'}}]}

    async def add_facts(email, facts):
        seen["facts"] = list(facts)
        return len(facts)

    async def add_notes(*a, **k):
        seen["notes"] = True
        return 1

    monkeypatch.setattr(agent_memory, "list_facts", facts)
    monkeypatch.setattr(agent_memory, "_complete", complete)
    monkeypatch.setattr(agent_memory, "add_facts", add_facts)
    monkeypatch.setattr(agent_memory, "add_notes", add_notes)
    monkeypatch.setattr(agent_memory, "_last_reflect", {})


def _run_stated(text=FACT):
    asked = []

    async def token_for():
        asked.append(1)
        return "tok"

    async def go():
        task = agent_memory.schedule_stated_facts("a@b.c", text, token_for)
        if task is not None:
            await task
        return task

    return asyncio.run(go()), asked


def test_a_fact_stated_to_the_free_model_is_kept_as_a_fact_only(monkeypatch):
    seen = {}
    _memory_offline(monkeypatch, seen)
    _jev_says(monkeypatch, True)
    task, asked = _run_stated()
    assert task is not None and asked == [1]
    assert seen["facts"] == ["Their project codename is Bluebird."]
    assert "notes" not in seen                      # no agent, no notes


def test_nothing_is_spent_unless_jev_is_sure(monkeypatch):
    """Review 2026-11-13: an unsure or absent Jev used to buy a completion."""
    for verdict in (None, False):
        seen = {}
        _memory_offline(monkeypatch, seen)
        _jev_says(monkeypatch, verdict)
        _task, asked = _run_stated()
        assert asked == [] and "facts" not in seen


def test_the_slot_is_its_own_and_taken_only_when_spent(monkeypatch):
    """A chatty message Jev turns down must not use the slot, and the slot
    is not the assistant's (review 2026-11-13)."""
    seen = {}
    _memory_offline(monkeypatch, seen)
    _jev_says(monkeypatch, False)
    _run_stated()
    assert agent_memory._last_reflect == {}
    _jev_says(monkeypatch, True)
    _run_stated()
    keys = list(agent_memory._last_reflect)
    assert [k[1] for k in keys] == [agent_memory.STATED_KEY]
    assert agent_memory.STATED_KEY != main_assistant.ASSISTANT_ID


def test_the_prompt_ignores_text_to_translate_or_rewrite():
    p = agent_memory.stated_facts_prompt([], "Translate to Spanish: I am 45")
    for words in ("translated", "rewritten", "summarised", "quoted",
                  "THEMSELVES"):
        assert words in p


@pytest.mark.parametrize("text", ["hi", "thanks!", "what is 2+2?"])
def test_small_or_short_messages_are_not_remembered(monkeypatch, text):
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    assert rt._remember_free_turn(_Body(text), text) is None


def test_remembering_has_its_own_switch(monkeypatch):
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setenv("MAIN_CHAT_REMEMBER", "0")
    assert rt._remember_free_turn(_Body(FACT), FACT) is None


def test_the_route_hands_the_message_to_the_stated_facts_path(monkeypatch):
    got = {}

    def schedule(email, text, token_for):
        got.update(email=email, text=text, token_for=token_for)
        return "task"

    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_memory, "schedule_stated_facts", schedule)
    assert rt._remember_free_turn(_Body(FACT), FACT) == "task"
    assert got["email"] == "owner@example.com" and got["text"] == FACT


def test_the_token_is_minted_for_the_person_only(monkeypatch):
    async def uid(email):
        return "user-1"

    async def stamp(user_id):
        return None

    monkeypatch.setattr(rt.agent_memory, "_owui_user_id", uid)
    monkeypatch.setattr(rt, "session_stamp_for", stamp)
    minted = {}
    monkeypatch.setattr(rt, "mint_owui_token",
                        lambda u, ttl_seconds, session_stamp: minted.update(
                            u=u, ttl=ttl_seconds) or "tok")
    assert asyncio.run(rt._free_turn_token("a@b.c")) == "tok"
    assert minted == {"u": "user-1", "ttl": rt.FREE_TURN_TOKEN_SECONDS}


def test_the_free_model_path_schedules_remembering(monkeypatch):
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
    out = asyncio.run(rt._route_chat(_Body(FACT)))
    assert out["turns"] == []
    assert calls == [FACT]


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


# --- review fixes (2026-11-13) -------------------------------------------------------

def test_publish_is_only_for_apps_built_here():
    pub = app_triage.PLATFORM["publish"]
    assert "App Builder" in pub.note and "somewhere else" in pub.note
    assert "connect Vercel" in pub.how


def test_a_reply_that_said_publish_counts_as_offered():
    msgs = [{"role": "user", "content": "put my site online"},
            {"role": "assistant", "content": "Click Publish in the App Builder."},
            {"role": "user", "content": "thanks!"}]
    assert "publish" in app_triage.already_offered(msgs)


def test_skill_names_are_matched_strictly():
    msgs = [{"role": "assistant", "content": "I made you a spreadsheet."},
            {"role": "user", "content": "x"}]
    assert app_triage.skills_offered(msgs, ["spreadsheet"]) == set()
    msgs[0]["content"] = "The spreadsheet skill fits, and weekly-review too."
    assert app_triage.skills_offered(msgs, ["spreadsheet", "weekly-review"]) == {
        "spreadsheet", "weekly-review"}


def test_a_skill_brings_its_own_tools_the_person_has(monkeypatch):
    seen = _wire(monkeypatch)
    pool = {"inbox-triage": {"name": "inbox-triage", "tools": ["gmail", "outlook"],
                             "description": "Sort the inbox."}}
    triage = {"picks": [], "connected": {"gmail"},
              "skills": [("inbox-triage", 0.98)], "pool": pool}
    asyncio.run(rt._assistant_reply(_Body("sort my inbox"), "sort my inbox",
                                    [], picked=[], triage=triage))
    assert seen["tool_ids"] == ["skills", "gmail"]      # outlook: not theirs
    assert seen["pinned"] == ["skills", "gmail"]        # kept for "yes, do it"


def test_the_status_line_does_not_claim_the_added_skill_tools(monkeypatch):
    _wire(monkeypatch)
    triage = {"picks": [], "connected": set(),
              "skills": [("weekly-review", 0.95)], "pool": POOL}
    out = asyncio.run(rt._assistant_reply(_Body("review my week"),
                                          "review my week", [], picked=[],
                                          triage=triage))
    assert out.get("status", "") == ""


def test_both_plans_get_their_buttons(monkeypatch):
    """A Publish pick must not cost a can_do answer its Connect button."""
    _wire(monkeypatch, answer="Sure.")
    can_plan = app_triage.plan([("linkedin", 0.99)], set(), [])
    import can_do

    async def facts(email, asked):
        return "FACTS", can_plan

    monkeypatch.setattr(rt.can_do, "question", lambda text: "asked")
    monkeypatch.setattr(rt, "_can_do_facts", facts)
    monkeypatch.setattr(rt.can_do, "reconnect_buttons", lambda a, p: a)
    triage = {"picks": [("publish", 0.9)], "connected": set(), "skills": [],
              "pool": {}}
    out = asyncio.run(rt._assistant_reply(
        _Body("can you post on linkedin and put my site online"),
        "can you post on linkedin and put my site online", [], picked=[],
        triage=triage))
    said = out["turns"][0]["answer"]
    assert "#aiui-connect:linkedin" in said
    assert app_triage.PLATFORM["publish"].how in said


def test_the_skill_pick_is_timeboxed(monkeypatch):
    monkeypatch.setattr(rt.agent_decider, "_key", lambda: "k")
    monkeypatch.setattr(rt, "SKILL_PICK_SECONDS", 0.05)
    monkeypatch.setattr(rt.agent_skills, "load_all", lambda: POOL)

    async def slow(*a, **k):
        await asyncio.sleep(1)
        return [("weekly-review", 0.99)]

    monkeypatch.setattr(rt.agent_jev, "pick_skills_for_message", slow)
    assert asyncio.run(rt._skills_for("a@b.c", "x", "")) == ({}, [])


def test_vercel_is_its_own_entry_with_its_own_how():
    """Asked about Publish alone, "deploy it to Vercel" scored 0.46 to 0.51
    even after a build; as its own entry 0.92 (2026-11-13)."""
    v = app_triage.PLATFORM["vercel"]
    assert "Vercel" in v.how and "connect Vercel" in v.how
    assert "Publish" in v.how and "App Builder" in v.how
    p = app_triage.plan([("vercel", 0.92)], set(), [])
    out = app_triage.with_buttons("Sure, here is how.", p)
    assert out.rstrip().endswith(v.how)


def test_publish_and_vercel_together_show_publish_unless_vercel_was_said():
    """"put it online" scored Publish 0.95 and Vercel 0.87; Publish's line
    already mentions Vercel, so only it is shown, unless they said Vercel."""
    p = app_triage.plan([("publish", 0.95), ("vercel", 0.87)], set(), [],
                        text="how do I put it online")
    assert [x["id"] for x in p["platform"]] == ["publish"]
    p = app_triage.plan([("publish", 0.6), ("vercel", 0.92)], set(), [],
                        text="can I deploy it to Vercel?")
    assert [x["id"] for x in p["platform"]] == ["vercel", "publish"]
