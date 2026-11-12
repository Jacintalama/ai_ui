"""The triage agent (Lukas, 2026-11-12): Jev sees every app the platform can
connect, connected or not, and the main chat recommends the right one with a
Connect button. Design: docs/plans/2026-11-12-triage-agent-design.md.
"""
import asyncio

import pytest

import agent_jev
import app_triage
import connections
import mytools
import routes_agent_turn as rt


# --- the catalogue tells the truth -------------------------------------------

def test_every_app_the_platform_can_connect_is_in_the_catalogue():
    """An app missing here can never be recommended, however well it fits."""
    connectable = set(connections.PROVIDERS) | {"gmail", "calendar", "gdrive"}
    assert set(app_triage.APPS) == connectable


def test_every_can_line_rests_on_tools_that_exist():
    """No guessing: an 'IO can' sentence names its tools, and they are real."""
    for app in app_triage.APPS.values():
        assert app.tools, f"{app.id} claims abilities with no tools behind them"
        if app.id in mytools.PROVIDER_TOOLS:
            real = {t.name for t in mytools.PROVIDER_TOOLS[app.id]}
        else:
            real = {app.id} if app.id in agent_jev.TOOL_NOTES else set()
        missing = set(app.tools) - real
        assert not missing, f"{app.id} names tools that do not exist: {missing}"


def test_read_only_apps_say_what_they_cannot_do():
    """Measured 2026-11-12: these have no tool that writes."""
    for app_id in ("airtable", "notion", "n8n"):
        assert app_triage.APPS[app_id].cannot, app_id


def test_airtable_does_not_claim_to_write():
    writes = {"create", "add", "update", "write", "delete"}
    names = {t.name for t in mytools.PROVIDER_TOOLS["airtable"]}
    assert not any(w in n for n in names for w in writes), (
        "Airtable can write now: update its can/cannot lines")
    assert "add" in app_triage.APPS["airtable"].cannot


def test_n8n_and_zapier_are_offered_as_a_choice_with_pros_and_cons():
    n8n, zapier = app_triage.APPS["n8n"], app_triage.APPS["zapier"]
    assert n8n.group and n8n.group == zapier.group
    assert "self-host" in n8n.pros.lower()
    assert "hosted" in zapier.pros.lower()


# --- the Jev question ----------------------------------------------------------

def test_one_yes_no_per_app_in_the_catalogue_order():
    state, questions = agent_jev.apps_request("save my leads somewhere")
    assert list(questions) == [f"a{i}" for i in range(len(app_triage.APPS))]
    for qid, app in zip(questions, app_triage.APPS.values()):
        q = questions[qid]
        assert q["type"] == "noul"
        assert app.label in q["instructions"]
        assert app.note in q["instructions"]
    assert "save my leads somewhere" in state


def test_the_question_reads_the_conversation_before_the_message():
    state, _ = agent_jev.apps_request("yes do that", context="I need to store leads")
    assert state.index("I need to store leads") < state.index("yes do that")


def _answers(scores):
    return {f"a{i}": agent_jev.Answer(choice=None, value=v, model="m",
                                      input_tokens=1)
            for i, v in enumerate(scores)}


def test_pick_apps_keeps_what_jev_is_sure_of_best_first(monkeypatch):
    ids = list(app_triage.APPS)
    scores = [0.0] * len(ids)
    scores[ids.index("airtable")] = 0.91
    scores[ids.index("hubspot")] = 0.97
    scores[ids.index("notion")] = agent_jev.cut(agent_jev.PURPOSE_APPS) - 0.01

    async def ask_many(email, purpose, state, questions, outcome=None):
        assert purpose == agent_jev.PURPOSE_APPS
        got = _answers(scores)
        if outcome:
            outcome(got)
        return got

    monkeypatch.setattr(agent_jev, "ask_many", ask_many)
    got = asyncio.run(agent_jev.pick_apps("a@b.c", "save my leads"))
    assert got == [("hubspot", 0.97), ("airtable", 0.91)]


def test_pick_apps_is_none_when_jev_cannot_be_asked(monkeypatch):
    async def ask_many(*a, **k):
        return None

    monkeypatch.setattr(agent_jev, "ask_many", ask_many)
    assert asyncio.run(agent_jev.pick_apps("a@b.c", "save my leads")) is None


def test_pick_apps_asks_nothing_about_an_empty_message(monkeypatch):
    async def ask_many(*a, **k):
        raise AssertionError("asked about nothing")

    monkeypatch.setattr(agent_jev, "ask_many", ask_many)
    assert asyncio.run(agent_jev.pick_apps("a@b.c", "   ")) == []


def test_the_app_cut_is_its_own_and_can_be_overridden(monkeypatch):
    assert agent_jev.PURPOSE_APPS in agent_jev.CUTS
    monkeypatch.setenv("JEV_CUT_APP_PICK", "0.9")
    assert agent_jev.cut(agent_jev.PURPOSE_APPS) == 0.9


# --- the plan -------------------------------------------------------------------

def test_a_plan_marks_what_is_connected():
    p = app_triage.plan([("airtable", 0.9), ("gmail", 0.8)], {"gmail"}, [])
    assert [(a["id"], a["connected"]) for a in p["apps"]] == [
        ("airtable", False), ("gmail", True)]


def test_a_plan_keeps_at_most_three_apps_best_first():
    picks = [("trello", 0.8), ("clickup", 0.95), ("notion", 0.9),
             ("github", 0.85)]
    p = app_triage.plan(picks, set(), [])
    assert [a["id"] for a in p["apps"]] == ["clickup", "notion", "github"]


def test_one_side_of_a_choice_brings_the_other():
    p = app_triage.plan([("n8n", 0.9)], set(), [])
    assert [a["id"] for a in p["apps"]] == ["n8n", "zapier"]


def test_unknown_ids_are_ignored():
    p = app_triage.plan([("myspace", 0.99), ("github", 0.8)], set(), [])
    assert [a["id"] for a in p["apps"]] == ["github"]


def test_the_features_the_tool_pick_chose_are_in_the_plan():
    p = app_triage.plan([("gmail", 0.9)], {"gmail"}, ["schedules", "gmail"])
    assert any("timer" in f for f in p["features"])


def test_the_assistant_is_needed_only_for_an_app_not_connected():
    assert app_triage.needs_assistant(
        app_triage.plan([("airtable", 0.9)], set(), []))
    assert not app_triage.needs_assistant(
        app_triage.plan([("gmail", 0.9)], {"gmail"}, []))
    assert not app_triage.needs_assistant(app_triage.plan([], set(), []))
    assert not app_triage.needs_assistant(None)


# --- the brief ------------------------------------------------------------------

def test_the_brief_says_connected_or_not_and_what_io_can_and_cannot_do():
    p = app_triage.plan([("airtable", 0.9), ("hubspot", 0.85)], set(), [])
    b = app_triage.brief(p)
    air = app_triage.APPS["airtable"]
    assert "Airtable" in b and "HubSpot" in b
    assert "not connected" in b
    assert air.can in b and air.cannot in b
    assert "Connect button" in b


def test_the_brief_compares_a_choice():
    b = app_triage.brief(app_triage.plan([("zapier", 0.9)], set(), []))
    assert app_triage.APPS["n8n"].pros in b
    assert app_triage.APPS["zapier"].pros in b


def test_no_apps_no_brief():
    assert app_triage.brief(app_triage.plan([], set(), [])) == ""


# --- the buttons ----------------------------------------------------------------

AIR = "[Connect Airtable](#aiui-connect:airtable)"


def test_a_recommended_app_not_connected_gets_its_button():
    p = app_triage.plan([("airtable", 0.9)], set(), [])
    out = app_triage.with_buttons("Airtable is a good place for your leads.", p)
    assert out.rstrip().endswith(AIR)


def test_a_button_is_never_doubled():
    p = app_triage.plan([("airtable", 0.9)], set(), [])
    said = "Use Airtable.\n\n" + AIR
    assert app_triage.with_buttons(said, p).count("#aiui-connect:airtable") == 1


def test_an_app_the_answer_never_named_is_introduced():
    p = app_triage.plan([("airtable", 0.9)], set(), [])
    out = app_triage.with_buttons("Here is how I would do it.", p)
    assert "Recommended: Airtable" in out
    assert AIR in out


def test_a_connected_app_gets_no_button():
    p = app_triage.plan([("gmail", 0.9)], {"gmail"}, [])
    assert app_triage.with_buttons("Reading Gmail.", p) == "Reading Gmail."


def test_both_sides_of_a_choice_get_a_button():
    p = app_triage.plan([("n8n", 0.9)], set(), [])
    out = app_triage.with_buttons("n8n or Zapier would both work.", p)
    assert "#aiui-connect:n8n" in out and "#aiui-connect:zapier" in out


# --- the main chat --------------------------------------------------------------

class _Body:
    user_email = "owner@example.com"
    chat_id = "chat-1"
    route_only = True
    first_only = False
    agent_id = None

    def __init__(self, text, context=None):
        self.messages = list(context or []) + [{"role": "user", "content": text}]


LEADS = "find a bunch of customers and save them somewhere"


def _wire(monkeypatch, answer="Airtable fits.", pending=None):
    seen = {}

    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        seen["graph"], seen["tool_ids"] = graph, tool_ids
        out = {"agent": agent, "answer": answer, "notes": []}
        if pending:
            out["pending"] = pending
        return out

    async def graph_block(_email, _text):
        return "GRAPH"

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    return seen


def test_an_app_not_connected_makes_the_assistant_answer_with_no_tool(monkeypatch):
    seen = _wire(monkeypatch)
    triage = {"picks": [("airtable", 0.9)], "connected": set()}
    out = asyncio.run(rt._assistant_reply(_Body(LEADS), LEADS, [], picked=[],
                                          triage=triage))
    assert out is not None
    assert seen["tool_ids"] == []
    assert seen["graph"].startswith("GRAPH")
    assert app_triage.APPS["airtable"].can in seen["graph"]
    assert out["turns"][0]["answer"].rstrip().endswith(AIR)


def test_with_tools_picked_the_brief_rides_along(monkeypatch):
    seen = _wire(monkeypatch, answer="I will check Gmail every morning.")
    triage = {"picks": [("gmail", 0.9)], "connected": {"gmail"}}
    out = asyncio.run(rt._assistant_reply(
        _Body("every 8am read my email"), "every 8am read my email", [],
        picked=["schedules", "gmail"], triage=triage))
    assert seen["tool_ids"] == ["schedules", "gmail"]
    assert "Gmail" in seen["graph"] and "timer" in seen["graph"]
    assert "#aiui-connect" not in out["turns"][0]["answer"]


def test_only_connected_apps_and_no_tool_leave_it_to_the_free_model(monkeypatch):
    _wire(monkeypatch)
    triage = {"picks": [("gmail", 0.9)], "connected": {"gmail"}}
    out = asyncio.run(rt._assistant_reply(_Body("hi"), "hi", [], picked=[],
                                          triage=triage))
    assert out is None


def test_no_triage_behaves_as_before(monkeypatch):
    seen = _wire(monkeypatch, answer="Done.")
    out = asyncio.run(rt._assistant_reply(_Body("x"), "x", [], picked=["gmail"]))
    assert out["turns"][0]["answer"] == "Done."
    assert seen["graph"] == "GRAPH"
    assert asyncio.run(rt._assistant_reply(_Body("x"), "x", [], picked=[])) is None


def test_a_turn_waiting_for_approval_gets_no_buttons(monkeypatch):
    held = {"calls": [{"name": "x"}], "agent_id": "io-assistant"}
    _wire(monkeypatch, answer="May I?", pending=held)
    triage = {"picks": [("airtable", 0.9)], "connected": set()}
    out = asyncio.run(rt._assistant_reply(_Body(LEADS), LEADS, [], picked=[],
                                          triage=triage))
    assert "#aiui-connect" not in out["turns"][0]["answer"]


def test_triage_pick_reads_jev_and_connections_together(monkeypatch):
    async def pick_apps(email, text, context=""):
        assert email == "owner@example.com" and text == LEADS
        return [("airtable", 0.9)]

    async def connected(email):
        return {"gmail"}

    import routes_agents
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda agent: True)
    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    got = asyncio.run(rt._triage_pick(_Body(LEADS), LEADS))
    assert got == {"picks": [("airtable", 0.9)], "connected": {"gmail"}}


def test_nothing_picked_reads_no_connections(monkeypatch):
    """Most messages fit no app: no database read for them."""
    async def pick_apps(email, text, context=""):
        return []

    async def connected(email):
        raise AssertionError("read connections for nothing")

    import routes_agents
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda agent: True)
    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    got = asyncio.run(rt._triage_pick(_Body(LEADS), LEADS))
    assert got == {"picks": [], "connected": set()}


@pytest.mark.parametrize("why", ["off", "greeting", "switch", "jev_down", "boom"])
def test_triage_pick_steps_aside(monkeypatch, why):
    async def pick_apps(email, text, context=""):
        if why == "boom":
            raise RuntimeError("bad")
        return None if why == "jev_down" else [("airtable", 0.9)]

    async def connected(email):
        return set()

    import routes_agents
    monkeypatch.setattr(rt, "_assistant_on", lambda: why != "off")
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda agent: True)
    monkeypatch.setattr(rt.agent_jev, "pick_apps", pick_apps)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    if why == "switch":
        monkeypatch.setenv("MAIN_CHAT_TRIAGE", "0")
    text = "hi" if why == "greeting" else LEADS
    assert asyncio.run(rt._triage_pick(_Body(text), text)) is None


def test_the_main_chat_asks_the_three_questions_and_hands_on_the_triage(monkeypatch):
    calls = {}

    async def agents_for(email):
        return []

    async def no_pin(key):
        return None

    async def tool_pick(body, text):
        calls["tool_pick"] = True
        return []

    async def triage_pick(body, text):
        calls["triage_pick"] = True
        return {"picks": [("airtable", 0.9)], "connected": set()}

    async def assistant_reply(body, text, agents, picked=None, triage=None):
        calls["reply"] = (picked, triage)
        return {"turns": [{"agent": None, "answer": "ok"}]}

    async def jev_release(*a):
        return False

    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_jev_release", jev_release)
    monkeypatch.setattr(rt, "_agents_for", agents_for)
    monkeypatch.setattr(rt, "_read_pin", no_pin)
    monkeypatch.setattr(rt, "_agents_may_take_unnamed", lambda: False)
    monkeypatch.setattr(rt, "_tool_pick", tool_pick)
    monkeypatch.setattr(rt, "_triage_pick", triage_pick)
    monkeypatch.setattr(rt, "_assistant_reply", assistant_reply)
    out = asyncio.run(rt._route_chat(_Body(LEADS)))
    assert out["turns"][0]["answer"] == "ok"
    assert calls["tool_pick"] and calls["triage_pick"]
    assert calls["reply"] == ([], {"picks": [("airtable", 0.9)],
                                   "connected": set()})


# --- calibration (scripts/jev_checks_calibrate.py apps) -------------------------

def _cal():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "scripts", "jev_checks_calibrate.py")
    spec = importlib.util.spec_from_file_location("jev_cal_apps", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_calibration_case_names_real_apps():
    cal = _cal()
    for msg, needs, fine in cal.APP_CASES:
        for app in set().union(*needs, fine) if needs else fine:
            assert app in app_triage.APPS, (msg, app)


def test_lukas_examples_are_calibration_cases():
    msgs = " ".join(c[0] for c in _cal().APP_CASES)
    for words in ("save them somewhere", "every 8am", "keep every version",
                  "automation workflow"):
        assert words in msgs


def test_a_need_is_met_by_any_one_of_its_apps():
    cal = _cal()
    assert cal.app_score({"trello": 0.9}, [{"notion", "trello"}], set(),
                         0.8) == (0, 0)
    assert cal.app_score({"github": 0.9}, [{"notion"}], set(), 0.8) == (1, 1)
    assert cal.app_score({"github": 0.9}, [], {"github"}, 0.8) == (0, 0)


def test_the_cut_is_the_lowest_clean_one_plus_a_step():
    cal = _cal()
    clean_from_07 = {c: (0 if c >= 0.7 else 2) for c in cal.UP}
    assert cal.choose_app_cut([clean_from_07, clean_from_07]) == 0.75
    never = {c: 1 for c in cal.UP}
    assert cal.choose_app_cut([never]) > 1


# --- the platform's own timer comes before a third-party one ---------------------

def test_a_timer_job_uses_the_platforms_schedules_not_n8n_or_zapier():
    """Lukas, 2026-11-12: "every 8 a.m., read my email ... it's going to use
    cron jobs and it's going to use Gmail integration". Measured live: Jev
    scored n8n 0.96, Gmail 0.92, Zapier 0.90 for that message, and the tool
    pick chose schedules 0.78 and gmail 0.98."""
    p = app_triage.plan([("n8n", 0.96), ("gmail", 0.92), ("zapier", 0.90)],
                        set(), ["gmail", "account", "schedules"],
                        text="every 8am read my email and send me a summary")
    assert [a["id"] for a in p["apps"]] == ["gmail"]
    assert any("timer" in f for f in p["features"])


def test_a_named_automation_app_is_kept_even_on_a_timer():
    p = app_triage.plan([("zapier", 0.95)], set(), ["schedules"],
                        text="every Monday post my sales numbers to Zapier")
    assert [a["id"] for a in p["apps"]] == ["zapier", "n8n"]


def test_without_a_timer_the_automation_choice_stays():
    """'I need an automation workflow that connects my apps': the tool pick
    chose nothing (account 0.71 was the top) and Jev scored n8n and Zapier
    0.97 each."""
    p = app_triage.plan([("n8n", 0.97), ("zapier", 0.97)], set(), [],
                        text="I need an automation workflow that connects my apps")
    assert [a["id"] for a in p["apps"]] == ["n8n", "zapier"]


def test_the_cut_is_the_measured_one():
    """scripts/jev_checks_calibrate.py apps 2, 2026-11-12 on jev-1.13.0:
    0.90 was the only cut with no wrong pick in either run, and no need was
    missed at it."""
    assert agent_jev.CUTS[agent_jev.PURPOSE_APPS] == 0.9


def test_the_main_chat_hands_the_message_to_the_plan(monkeypatch):
    seen = _wire(monkeypatch, answer="I'll set a daily job that reads Gmail.")
    triage = {"picks": [("n8n", 0.96), ("gmail", 0.92)], "connected": set()}
    text = "every 8am read my email and send me a summary"
    out = asyncio.run(rt._assistant_reply(_Body(text), text, [],
                                          picked=["gmail", "schedules"],
                                          triage=triage))
    said = out["turns"][0]["answer"]
    assert "#aiui-connect:gmail" in said
    assert "n8n" not in said and "n8n" not in seen["graph"]
