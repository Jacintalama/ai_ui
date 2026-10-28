"""The main chat, smooth and fast (2026-10-28).

Three things seen live: a reply opened with the robot and the name twice,
because the previous replies' pictures were fed back as history and the
model copied them; Mia asked to run ask_agents on "hi team", a round inside
a round, because the Ask Your Agents tool is installed under an id the bar
did not know; and every message paged the agent list twice and read the
memory, the clock and the graph one after the other.
"""
from unittest.mock import AsyncMock

import pytest

import agent_access
import agent_avatar
import agent_routing as ar
import agent_runner
import agent_tools
import routes_agent_turn as rt

NAMES = ["Ada", "Mia"]
FACE = agent_avatar.reply_face("agent-ada-1", "Ada")


# --- the pictures ------------------------------------------------------------

def test_a_face_line_is_removed_from_history_and_the_words_are_kept():
    rendered = FACE + "\n\nTwo invoices are due.\n\n" + agent_avatar.reply_face("agent-mia-1", "Mia") + "\n\nAll paid."
    assert ar.strip_label_lines(rendered, NAMES) == "Two invoices are due.\n\nAll paid."
    assert "data:image" not in ar.strip_label_lines(rendered, NAMES)


def test_a_picture_is_dropped_even_when_the_name_is_not_known():
    text = "![Zed](data:image/svg+xml;base64,AAAA) **Zed**\n\nhello"
    assert "data:image" not in ar.strip_label_lines(text, NAMES)
    assert ar.drop_data_images(text) == "**Zed**\n\nhello"
    assert ar.drop_data_images("no picture here") == "no picture here"
    assert ar.drop_data_images(None) == ""


def test_an_answer_that_echoes_the_face_loses_only_the_leading_one():
    echoed = FACE + "\n" + FACE + "\n\nHere is my workflow.\n\nSee **Ada** above."
    assert ar.strip_leading_labels(echoed, NAMES) == "Here is my workflow.\n\nSee **Ada** above."


def test_the_rendered_reply_with_faces_survives_a_round_trip_through_cleaning():
    turns = [{"agent": {"id": "agent-ada-1", "name": "Ada"}, "answer": "Two due.", "notes": []},
             {"agent": {"id": "agent-mia-1", "name": "Mia"}, "answer": "All paid.", "notes": []}]
    rendered = rt.render_turns(turns, faces=True)
    assert rendered.count("data:image/svg+xml;base64,") == 2
    history = ar.clean_history_for_agent([{"role": "assistant", "content": rendered}], NAMES)
    assert history[0]["content"] == "Two due.\n\nAll paid."


# --- the agents tool inside a turn -------------------------------------------------

async def test_ask_agents_is_refused_inside_an_agents_turn_whatever_the_row_is_called():
    outcome = agent_tools.ToolOutcome()
    call = {"id": "c1", "type": "function", "function": {"name": "ask_agents", "arguments": '{"message": "hi team"}'}}
    said = await agent_tools.execute_tool_call(call, "o@example.com", ["ask_your_agents"],
                                               "agent-mia-1", outcome=outcome)
    assert "cannot ask the agents from inside its own turn" in said
    assert outcome.status == agent_tools.agent_activity.STEP_REFUSED


async def test_an_asking_agent_is_not_asked_for_approval_to_loop():
    """On Ask, a write is held for the owner. This is not a write to hold,
    it is a loop: the model is told no and answers some other way."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "ask_agents", "arguments": '{"message": "hi team"}'}}]},
                "finish_reason": "tool_calls"}]}
        return {"choices": [{"message": {"content": "Hi! Mia here.", "tool_calls": None},
                             "finish_reason": "stop"}]}

    agent_runner._post_chat, kept = fake_post, agent_runner._post_chat
    try:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-mia-1", messages=[{"role": "user", "content": "hi team"}],
            tool_ids=["ask_your_agents"], user_email="o@example.com",
            tool_mode=agent_access.MODE_ASK)
    finally:
        agent_runner._post_chat = kept
    assert answer == "Hi! Mia here."
    fed_back = [m for m in posts[1]["messages"] if m.get("role") == "tool"]
    assert fed_back and "cannot ask the agents" in fed_back[0]["content"]


async def test_the_tool_is_dropped_from_what_an_agent_may_reach_by_its_title(monkeypatch):
    import routes_agents

    async def listed(email):
        return {"tools": [{"id": "gmail", "label": "Gmail"},
                          {"id": "agents", "label": "Agents"},
                          {"id": "ask_your_agents_v2", "label": "Ask Your Agents"},
                          {"id": "agent_builder", "label": "Agent Builder"}]}
    monkeypatch.setattr(routes_agents, "tools_for_email", listed)
    assert await rt._every_tool_for("o@example.com") == ["gmail", "agent_builder"]


# --- one listing per message, reads side by side ----------------------------------

@pytest.fixture
def _turn(monkeypatch):
    seen = {}
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(side_effect=AssertionError("listed again")))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=["gmail"]))

    async def chat(**kw):
        seen["chat"] = kw
        return ("Hello.", [])
    monkeypatch.setattr(rt, "_chat", chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", AsyncMock(return_value="run-1"))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(rt.agent_memory, "schedule_reflection", lambda *a, **k: None)
    return seen


ADA = {"id": "agent-ada-1", "name": "Ada", "user_id": "u1", "base_model_id": "gpt-5",
       "meta": {"toolIds": ["gmail"]}, "params": {"system": "Be Ada."}}


async def test_a_turn_handed_the_listing_does_not_page_open_webui_again(_turn):
    token, tools, level, agent, roster = await rt._resolve_agent_row(
        "o@example.com", "agent-ada-1", listing=[ADA])
    assert agent is ADA and roster == [ADA] and tools == ["gmail"]


async def test_the_chat_round_hands_its_listing_to_the_turn(_turn, monkeypatch):
    monkeypatch.setattr(rt.agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(rt, "clock_for", AsyncMock(return_value=None))
    out = await rt._turn_for("o@example.com", ADA, [{"role": "user", "content": "hi"}],
                             names=["Ada"], roster=[ADA])
    # _list_agents raises if called; the turn ran on the listing instead.
    assert out["answer"] == "Hello." and _turn["chat"]["agent"] is ADA
    # And nothing leaks out of the turn.
    assert rt._listing_for_turn.get() is None


async def test_memory_and_clock_are_read_side_by_side(monkeypatch):
    import asyncio
    order = []

    async def memory(email, agent_id):
        order.append("memory start")
        await asyncio.sleep(0.05)
        order.append("memory end")
        return ""

    async def clock(email):
        order.append("clock start")
        await asyncio.sleep(0.05)
        order.append("clock end")
        return None

    monkeypatch.setattr(rt.agent_memory, "recall_block", memory)
    monkeypatch.setattr(rt, "clock_for", clock)
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(return_value={"answer": "x", "notes": []}))
    await rt._turn_for("o@example.com", ADA, [{"role": "user", "content": "hi"}], names=["Ada"])
    assert order[:2] == ["memory start", "clock start"], order
