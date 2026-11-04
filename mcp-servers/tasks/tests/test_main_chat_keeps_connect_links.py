"""The main chat's assistant answer about skills keeps its Connect button
(2026-11-04). Measured live: the model read suggest_skills, then wrote
"There's a Connect button above if you want that" and dropped the link, so
nothing was on screen. The service now adds the link the answer talks about.
"""
import asyncio

import routes_agent_turn as rt

TRACKER_NEED = [{"app": "tracker", "label": "a task tracker (Trello, GitHub or ClickUp)",
                 "skills": ["daily-standup"], "connect": "#aiui-connect:trello",
                 "button": "Connect a task tracker"}]
DROPPED = ("A task tracker (Trello, GitHub or ClickUp) would add daily-standup. "
           "There's a Connect button above if you want that.")


class _Body:
    user_email = "owner@example.com"
    chat_id = "chat-1"
    route_only = True
    first_only = False
    agent_id = None

    def __init__(self, text):
        self.messages = [{"role": "user", "content": text}]


def _run(monkeypatch, answer, picked, needs=TRACKER_NEED):
    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        return {"agent": agent, "answer": answer, "notes": []}

    async def graph_block(_email, _text):
        return ""

    asked = []

    async def connect_needs(email):
        asked.append(email)
        return needs

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(rt, "_skill_connect_needs", connect_needs)
    out = asyncio.run(rt._assistant_reply(
        _Body("which skills should I use?"), "which skills should I use?", [],
        picked=picked))
    return out, asked


def test_a_dropped_connect_link_is_put_back(monkeypatch):
    out, asked = _run(monkeypatch, DROPPED, ["skills"])
    said = out["turns"][0]["answer"]
    assert said.startswith(DROPPED)
    assert said.rstrip().endswith("[Connect a task tracker](#aiui-connect:trello)")
    assert "[Connect a task tracker](#aiui-connect:trello)" in out["rendered_web"]
    assert asked == ["owner@example.com"]


def test_a_turn_without_the_skills_tool_is_left_alone(monkeypatch):
    """Not a skills answer, so the person's connections are not even read."""
    out, asked = _run(monkeypatch, "Connect your tracker in Settings.", ["gmail"])
    assert out["turns"][0]["answer"] == "Connect your tracker in Settings."
    assert asked == []


def test_a_kept_link_is_not_doubled(monkeypatch):
    kept = DROPPED + "\n\n[Connect a task tracker](#aiui-connect:trello)"
    out, _ = _run(monkeypatch, kept, ["skills"])
    assert out["turns"][0]["answer"].count("#aiui-connect:trello") == 1


def test_a_failure_reading_connections_leaves_the_answer_as_it_was(monkeypatch):
    async def boom(_email):
        raise RuntimeError("db down")

    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        return {"agent": agent, "answer": DROPPED, "notes": []}

    async def graph_block(_email, _text):
        return ""

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(rt, "_skill_connect_needs", boom)
    out = asyncio.run(rt._assistant_reply(
        _Body("which skills should I use?"), "which skills should I use?", [],
        picked=["skills"]))
    assert out["turns"][0]["answer"] == DROPPED


def test_the_needs_are_read_the_way_the_suggest_route_reads_them(monkeypatch):
    """Wiring: the real pool and connections, through skill_fit.overview."""
    import routes_agents

    async def pool(email):
        assert email == "owner@example.com"
        return {"daily-standup": {"name": "daily-standup",
                                  "tools": ["server:mcp-proxy"]},
                "inbox-triage": {"name": "inbox-triage", "tools": ["gmail"]}}

    async def connected(email):
        return {"gmail"}

    monkeypatch.setattr(routes_agents, "_skill_pool", pool)
    monkeypatch.setattr(routes_agents, "_connected_providers", connected)
    got = asyncio.run(rt._skill_connect_needs("owner@example.com"))
    assert [(n["app"], n["skills"], n["connect"]) for n in got] == [
        ("tracker", ["daily-standup"], "#aiui-connect:trello")]


def test_the_answer_measured_live_gets_its_button():
    """The words the model actually wrote on 2026-11-04, 13:44 UTC."""
    import skill_fit
    live = ("One gap worth noting: a task tracker connection (Trello, GitHub "
            "or ClickUp) would add skills like blocker-report, daily-standup "
            "and meeting-to-tasks, which would fit how your team (Ada, Dev, "
            "Mia) works. There's a Connect button above if you want that.")
    assert skill_fit.missing_links(live, TRACKER_NEED) == [
        "[Connect a task tracker](#aiui-connect:trello)"]
