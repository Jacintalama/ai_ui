"""The brief every surface builds, and the clock it carries.

Two faults this pins. An agent never knew what day it was: no datetime
reached any prompt, because the per-user clock is an Open WebUI inlet filter
and an agent turn does not pass through filters. A morning briefing on a
schedule could not tell today from last Tuesday.

And the brief itself reached one surface of the four. These tests build it
directly, the way a schedule and a bot gateway now do, rather than through
the chat path that was the only caller.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import agent_brief

MANILA = ZoneInfo("Asia/Manila")
ADA = {"id": "agent-a", "name": "Ada"}

# A Wednesday, deliberately: a weekday name nobody would reach for by
# accident, so a hardcoded string cannot pass this.
WHEN = datetime(2026, 9, 23, 20, 14, tzinfo=MANILA)


def test_the_brief_says_what_day_it_is():
    said = agent_brief.build(ADA, ["Ada"], now=WHEN)["content"]
    assert "Wednesday 23 September 2026" in said


def test_the_brief_says_the_time_and_whose_clock_it_is():
    """A schedule fires on its own timezone. Saying 8:14pm without saying
    where leaves an agent in Manila reporting a London morning."""
    said = agent_brief.build(ADA, ["Ada"], now=WHEN)["content"]
    assert "8:14pm" in said
    assert "Asia/Manila" in said


def test_a_single_digit_day_and_hour_carry_no_leading_zero():
    """strftime pads both. "Today is Friday 03 September, 08:05am" is not
    how a person writes it, and the brief is read by a model trained on how
    people write."""
    said = agent_brief.build(
        ADA, ["Ada"],
        now=datetime(2026, 9, 4, 8, 5, tzinfo=MANILA))["content"]
    assert "Friday 4 September 2026" in said
    assert "8:05am" in said
    assert "04 September" not in said


def test_the_clock_is_utc_when_nobody_says_otherwise():
    """Every surface passes a clock. A caller that forgets still gets a
    date rather than a brief that silently loses the sentence."""
    said = agent_brief.build(ADA, ["Ada"])["content"]
    assert "Today is" in said
    assert "UTC" in said


def test_an_unknown_timezone_falls_back_rather_than_raising():
    """The timezone is whatever the browser last reported into user_prefs,
    or whatever is typed on a schedule. A turn must not die over it."""
    assert agent_brief.now_in("Mars/Olympus").tzinfo == timezone.utc
    assert agent_brief.now_in("").tzinfo == timezone.utc
    assert agent_brief.now_in("Asia/Manila").tzinfo == MANILA


# ---------------------------------------------------------------------------
# The surfaces that had no brief at all. A schedule and a bot gateway each
# built their own leading system message out of the memory block alone, so
# neither could see a skill, the account, the roster or its own role.
# ---------------------------------------------------------------------------
from unittest.mock import AsyncMock                             # noqa: E402

import agent_graph                                              # noqa: E402
import agent_memory                                             # noqa: E402
import agent_runner                                             # noqa: E402

SKILLED = {"id": "agent-1", "name": "Ada",
           "meta": {"role": "Project manager", "skillIds": ["weekly-review"]}}


class _Sched:
    id = "s1"
    agent_id = "agent-1"
    user_email = "o@example.com"
    prompt = "Write the weekly review."
    last_result = ""
    last_run_status = None
    tool_mode = "read_only"
    tz = "Asia/Manila"


def _wire_schedule(monkeypatch, agent=None, graph="", memory=""):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([agent or SKILLED], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_runner.agent_activity, "start_run",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=memory))
    monkeypatch.setattr(agent_graph, "graph_block", AsyncMock(return_value=graph))
    import routes_agent_turn
    monkeypatch.setattr(routes_agent_turn, "tools_for_agent", AsyncMock(return_value=[]))
    return seen


async def test_a_schedule_run_carries_the_skills_it_was_given(monkeypatch):
    """The defect this whole change exists for. An agent set up with
    meta.skillIds = ["weekly-review"] ran its weekly cron without ever
    being shown the skill."""
    seen = _wire_schedule(monkeypatch)

    status, _result, _extras = await agent_runner.run_agent(_Sched())

    assert status == "completed"
    said = seen["messages"][0]["content"]
    assert seen["messages"][0]["role"] == "system"
    assert "ready-made instructions" in said
    assert "Weekly review" in said


async def test_a_schedule_run_knows_who_it_is_and_what_day_it_is(monkeypatch):
    seen = _wire_schedule(monkeypatch)

    await agent_runner.run_agent(_Sched())

    said = seen["messages"][0]["content"]
    assert "You are Ada, this person's project manager." in said
    assert "Today is" in said
    # The schedule's own zone, which is the clock the cron fired on.
    assert "Asia/Manila" in said


async def test_a_schedule_run_sees_what_the_person_has(monkeypatch):
    seen = _wire_schedule(monkeypatch, graph="They have 4 apps.")

    await agent_runner.run_agent(_Sched())

    assert "They have 4 apps." in seen["messages"][0]["content"]


async def test_a_schedule_is_not_told_about_a_room_it_is_not_in(monkeypatch):
    """The roster sentence says "the other assistants HERE". On a cron run
    nobody else is speaking, so naming a room would be a description of
    something that is not happening."""
    seen = _wire_schedule(monkeypatch)

    await agent_runner.run_agent(_Sched())

    assert "The other assistants here are" not in seen["messages"][0]["content"]


async def test_a_schedule_still_sends_the_task_last(monkeypatch):
    seen = _wire_schedule(monkeypatch)

    await agent_runner.run_agent(_Sched())

    assert seen["messages"][-1]["content"] == "Write the weekly review."


# ---------------------------------------------------------------------------
# The bot gateway. Discord, Slack and Telegram call /agents/turn directly
# (webhook-handler/clients/tasks.py), not the routing path, so this endpoint
# built its own leading system message out of the memory block alone.
# ---------------------------------------------------------------------------
import routes_agent_turn as rt                                  # noqa: E402


def _body(messages=None):
    class B:
        user_email = "o@example.com"
        agent_id = "agent-1"
    b = B()
    b.messages = messages if messages is not None else [
        {"role": "user", "content": "what is on today"}]
    return b


def _wire_bot(monkeypatch, agents=None, graph="", memory=""):
    """The bot gateway, driven through the real _run_turn.

    _run_turn is not faked here: the brief is built from the row and roster
    that _resolve_agent_row already fetched, which is the whole point of
    building it there, so a test that faked _run_turn would assert nothing.
    """
    seen = {}
    roster = agents if agents is not None else [
        SKILLED, {"id": "agent-2", "name": "Mia", "meta": {"role": "Receptionist"}}]

    async def resolve(email, agent_id):
        agent = next((a for a in roster if a.get("id") == agent_id), None)
        return "tok", [], "read", agent or {"id": agent_id}, roster

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "ok", []

    monkeypatch.setattr(rt, "_require_internal", lambda secret: None)
    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", AsyncMock(return_value=None))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=memory))
    monkeypatch.setattr(agent_memory, "schedule_reflection", lambda *a, **k: None)
    monkeypatch.setattr(agent_graph, "graph_block", AsyncMock(return_value=graph))
    monkeypatch.setattr(rt.routes_prefs, "read_timezone",
                        AsyncMock(return_value=("Asia/Manila", "browser")))
    return seen


async def test_a_bot_turn_carries_the_skills_the_agent_was_given(monkeypatch):
    seen = _wire_bot(monkeypatch)

    await rt.turn(_body(), x_internal_secret="s")

    said = seen["messages"][0]["content"]
    assert seen["messages"][0]["role"] == "system"
    assert "ready-made instructions" in said
    assert "Weekly review" in said


async def test_a_bot_turn_knows_its_own_name_role_and_the_others(monkeypatch):
    seen = _wire_bot(monkeypatch)

    await rt.turn(_body(), x_internal_secret="s")

    said = seen["messages"][0]["content"]
    assert "You are Ada, this person's project manager." in said
    assert "Mia (receptionist)" in said


async def test_a_bot_turn_uses_the_persons_own_clock(monkeypatch):
    seen = _wire_bot(monkeypatch)

    await rt.turn(_body(), x_internal_secret="s")

    assert "Asia/Manila" in seen["messages"][0]["content"]


async def test_a_bot_turn_sees_what_the_person_has(monkeypatch):
    seen = _wire_bot(monkeypatch, graph="They have 4 apps.")

    await rt.turn(_body(), x_internal_secret="s")

    assert "They have 4 apps." in seen["messages"][0]["content"]


async def test_the_person_s_own_message_still_arrives_after_the_brief(monkeypatch):
    seen = _wire_bot(monkeypatch)

    await rt.turn(_body(), x_internal_secret="s")

    assert seen["messages"][-1] == {"role": "user", "content": "what is on today"}


async def test_a_broken_memory_read_does_not_cost_the_bot_its_answer(monkeypatch):
    """Every optional part of the brief fails on its own. The identity and
    the skills come off the row, so they survive a dead memory store."""
    seen = _wire_bot(monkeypatch)
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(side_effect=RuntimeError("memory exploded")))

    out = await rt.turn(_body(), x_internal_secret="s")

    assert out["answer"] == "ok"
    assert "You are Ada" in seen["messages"][0]["content"]


# ---------------------------------------------------------------------------
# The room and the routing path. These always had a brief; what they did not
# have was a clock, and this is the one surface where the person is sitting
# there and knows perfectly well what day it is.
# ---------------------------------------------------------------------------
async def test_a_room_turn_uses_the_persons_own_clock(monkeypatch):
    seen = {}

    async def fake_run(user_email, agent_id, messages, brief=False):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(rt.routes_prefs, "read_timezone",
                        AsyncMock(return_value=("Asia/Manila", "browser")))

    await rt._turn_for("o@example.com", SKILLED,
                       [{"role": "user", "content": "what is on today"}], ["Ada"])

    assert "Asia/Manila" in seen["messages"][0]["content"]


async def test_a_room_turn_answers_even_with_no_timezone_stored(monkeypatch):
    """Nobody has a row until their browser reports one. UTC is a worse
    answer than their own zone and a far better one than no turn."""
    seen = {}

    async def fake_run(user_email, agent_id, messages, brief=False):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(rt.routes_prefs, "read_timezone",
                        AsyncMock(return_value=(None, None)))

    out = await rt._turn_for("o@example.com", SKILLED,
                             [{"role": "user", "content": "hi"}], ["Ada"])

    assert out["answer"] == "ok"
    assert "Today is" in seen["messages"][0]["content"]


async def test_a_round_reads_the_persons_clock_once_not_once_per_agent(monkeypatch):
    """read_timezone opens its own Postgres connection and closes it, so a
    per-agent read costs a connection per agent per message. Seven agents in
    a room is seven, which is the shape of the Open WebUI pool outage on
    2026-09-10. The account does not change between two agents answering one
    question, and neither does the clock, so it is read once and handed to
    everybody, exactly as the graph block is."""
    mia = {"id": "agent-m", "name": "Mia", "meta": {"role": "Receptionist"}}
    read = AsyncMock(return_value=("Asia/Manila", "browser"))

    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_agents_for", AsyncMock(return_value=[SKILLED, mia]))
    monkeypatch.setattr(rt, "_run_turn",
                        AsyncMock(return_value={"answer": "hi", "notes": []}))
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(agent_graph, "graph_block", AsyncMock(return_value=""))
    monkeypatch.setattr(rt.routes_prefs, "read_timezone", read)
    pins = {}
    monkeypatch.setattr(rt, "_read_pin", AsyncMock(side_effect=lambda k: pins.get(k)))
    monkeypatch.setattr(rt, "_write_pin",
                        AsyncMock(side_effect=lambda k, v: pins.__setitem__(k, v)))

    class B:
        user_email = "o@example.com"
        route_only = False
        first_only = False
        chat_id = "chat-1"
        messages = [{"role": "user", "content": "ada and mia, what is on today"}]

    out = await rt.chat(B(), x_internal_secret="s")

    assert len(out["turns"]) == 2, out["turns"]
    assert read.await_count == 1
