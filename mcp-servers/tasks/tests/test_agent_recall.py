"""What an agent starts a turn knowing.

The recall block rides at the end of the identity line so every surface that
builds a turn through _turn_for carries it: the main chat pipe and the panel.
The bots do not come that way. Discord, Slack and Telegram post to
/agents/turn, which calls _run_turn directly, so that endpoint has to add the
block itself and is tested here as its own path.
"""
from unittest.mock import AsyncMock

import agent_access
import agent_memory
import agent_runner
import routes_agent_turn as rt


def _agent():
    return {"id": "agent-1", "name": "Ada", "meta": {"toolIds": ["gmail"]}}


def _body(messages=None):
    """The shape /agents/turn is called with. A plain object rather than a
    TurnIn, the same way tests/test_agent_turn_endpoint.py builds it."""
    class B:
        user_email = "o@example.com"
        agent_id = "agent-1"
    b = B()
    b.messages = messages if messages is not None else [
        {"role": "user", "content": "hello there"}]
    return b


def test_an_empty_block_leaves_the_identity_line_byte_identical():
    before = rt._identity_line(_agent(), ["Ada"])
    after = rt._identity_line(_agent(), ["Ada"], memory="")
    assert before == after
    # Pinned rather than left to the comparison above, which on its own only
    # proves two calls down the same branch agree with each other. This says
    # what the last sentence of the line actually is, so a block that landed
    # anywhere but after it would be caught.
    assert before["content"].endswith("it is added for you.")


def test_the_block_is_appended_after_everything_else():
    # A skill on purpose: with no skill assigned the brief is empty, and
    # "after everything else" then proves only that it is after nothing.
    agent = dict(_agent(), meta={"toolIds": ["gmail"], "skillIds": ["inbox-triage"]})
    line = rt._identity_line(agent, ["Ada"], memory="Known about this person:\n- x")
    content = line["content"]
    assert content.endswith("Known about this person:\n- x")
    assert content.index("Skill: inbox-triage") < content.index("Known about this person")


async def test_turn_for_reads_memory_and_hands_it_to_the_line(monkeypatch):
    seen = {}

    async def fake_run(user_email, agent_id, messages):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    recall = AsyncMock(return_value="Known about this person:\n- likes tea")
    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block", recall)
    await rt._turn_for("o@example.com", _agent(),
                       [{"role": "user", "content": "hello there"}], ["Ada"])
    system = seen["messages"][0]
    assert system["role"] == "system"
    assert "likes tea" in system["content"]
    # Whose memory, and which agent's. Reading the right rows is the whole
    # feature, and a call that passed the wrong email would still put a block
    # in the line and still pass every assertion above.
    assert recall.await_args.args == ("o@example.com", "agent-1")


async def test_a_failed_memory_read_costs_the_memory_not_the_answer(monkeypatch):
    """recall_block promises never to raise, and _turn_for promises never to
    raise. A bug in the first must not spend the second: the person still
    gets their answer, it just arrives without the block."""
    monkeypatch.setattr(rt, "_run_turn",
                        AsyncMock(return_value={"answer": "ok", "notes": []}))
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(side_effect=RuntimeError("memory exploded")))

    out = await rt._turn_for("o@example.com", _agent(),
                             [{"role": "user", "content": "hello there"}], ["Ada"])

    assert out["agent"]["id"] == "agent-1"
    # The real answer, not the failure sentence: the optional read gets its
    # own try arm, so a broken read never reaches the turn's failure path.
    assert out["answer"] == "ok"


async def test_the_turn_endpoint_prepends_the_block_for_the_bots(monkeypatch):
    """Discord, Slack and Telegram post to /agents/turn and never reach
    _turn_for, so without this they were the three surfaces with no memory."""
    seen = {}

    async def fake_run(user_email, agent_id, messages):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_require_internal", lambda secret: None)
    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(return_value="Known about this person:\n- likes tea"))

    await rt.turn(_body(), x_internal_secret="s")

    assert seen["messages"][0]["role"] == "system"
    assert "likes tea" in seen["messages"][0]["content"]
    assert seen["messages"][1] == {"role": "user", "content": "hello there"}


async def test_the_turn_endpoint_sends_the_messages_untouched_when_nothing_is_stored(
        monkeypatch):
    seen = {}
    sent = [{"role": "user", "content": "hello there"}]

    async def fake_run(user_email, agent_id, messages):
        seen["messages"] = messages
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_require_internal", lambda secret: None)
    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))

    await rt.turn(_body(sent), x_internal_secret="s")

    assert seen["messages"] == sent


async def test_a_failed_memory_read_still_answers_the_bots(monkeypatch):
    """The same guarantee on the endpoint the bots actually call."""
    monkeypatch.setattr(rt, "_require_internal", lambda secret: None)
    monkeypatch.setattr(rt, "_run_turn",
                        AsyncMock(return_value={"answer": "ok", "notes": []}))
    monkeypatch.setattr(agent_memory, "recall_block",
                        AsyncMock(side_effect=RuntimeError("memory exploded")))

    out = await rt.turn(_body(), x_internal_secret="s")

    assert out == {"answer": "ok", "notes": []}


class _Sched:
    id = "s1"
    agent_id = "agent-1"
    user_email = "o@example.com"
    prompt = "Write the weekly review."
    last_result = ""
    last_run_status = None
    tool_mode = "read_only"


def _wire_schedule(monkeypatch, memory):
    """Every seam run_agent reaches for, with recall_block set to `memory`.

    Returns the dict the fake _chat records its keyword arguments into.
    """
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([{"id": "agent-1", "name": "Ada",
                                                  "meta": {"toolIds": []}}], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_runner.agent_activity, "start_run",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=memory))
    import routes_agent_turn
    monkeypatch.setattr(routes_agent_turn, "tools_for_agent", AsyncMock(return_value=[]))
    return seen


async def test_a_schedule_run_carries_the_block_as_the_leading_system_message(monkeypatch):
    seen = _wire_schedule(monkeypatch, "Known about this person:\n- likes tea")

    status, _result, _extras = await agent_runner.run_agent(_Sched())
    assert status == "completed"
    first = seen["messages"][0]
    assert first["role"] == "system" and "likes tea" in first["content"]
    assert seen["messages"][-1]["content"] == "Write the weekly review."


async def test_a_schedule_run_with_nothing_stored_sends_the_task_unchanged(monkeypatch):
    seen = _wire_schedule(monkeypatch, "")

    status, _result, _extras = await agent_runner.run_agent(_Sched())
    assert status == "completed"
    assert seen["messages"] == agent_runner._messages_for(_Sched())


# ---------------------------------------------------------------------------
# The agent ROW, not just its id. The free-model fallback and the no-reasoning
# payload both read base_model_id and params off the row, so a caller that
# hands the loop only a model id gets an agent that cannot fall back and that
# leaks its thinking into the answer. run_agent already passed it; the three
# chat callers did not, which is every turn a person actually types.
# ---------------------------------------------------------------------------


async def _wire_turn(monkeypatch, row, chat):
    """Every seam _run_turn and _resume_turn reach for, with `chat` as _chat."""
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([row], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "_chat", chat)
    monkeypatch.setattr(rt.agent_activity, "start_run", AsyncMock(return_value=None))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())
    # Task 8 adds this; patched with raising=False so this file is valid on
    # both sides of it, and so no test here opens a database it has not got.
    monkeypatch.setattr(agent_memory, "schedule_reflection",
                        lambda *a, **k: None, raising=False)


async def test_run_turn_hands_the_agent_row_to_the_loop(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {"system": "Be Ada."}, "meta": {"toolIds": []}}
    await _wire_turn(monkeypatch, row, fake_chat)

    await rt._run_turn("o@example.com", "agent-1", [{"role": "user", "content": "q"}])
    assert seen["agent"]["base_model_id"] == "x:free"
    assert seen["agent"]["params"]["system"] == "Be Ada."


async def test_resume_turn_hands_the_agent_row_to_the_loop(monkeypatch):
    """The held half of a turn runs on the same model as the first half."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {"system": "Be Ada."},
           "meta": {"toolIds": [], "access": "all"}}
    await _wire_turn(monkeypatch, row, fake_chat)

    await rt._resume_turn("o@example.com", "agent-1",
                          [{"role": "user", "content": "q"}], [], True)
    assert seen["agent"]["base_model_id"] == "x:free"


async def test_a_schedule_run_hands_the_agent_row_to_the_loop(monkeypatch):
    seen = _wire_schedule(monkeypatch, "")

    status, _result, _extras = await agent_runner.run_agent(_Sched())
    assert status == "completed"
    assert seen["agent"]["id"] == "agent-1"


async def test_resolve_agent_still_returns_three_values(monkeypatch):
    """Callers and tests predating the row read a 3-tuple."""
    row = {"id": "agent-1", "name": "Ada", "meta": {"toolIds": []}}
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([row], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))
    out = await rt._resolve_agent("o@example.com", "agent-1")
    assert len(out) == 3


# ---------------------------------------------------------------------------
# Capture. A chat turn that settled something schedules one detached
# completion to write it down. Only the chat turn: never the resume half,
# which has no new message of its own, and never a turn that stopped to ask,
# which has not happened yet.
# ---------------------------------------------------------------------------


async def test_run_turn_schedules_a_reflection_with_the_last_user_message(
        monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        return "Done, 7am it is.", []

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {"system": "Be Ada."}, "meta": {"toolIds": []}}
    await _wire_turn(monkeypatch, row, fake_chat)

    def fake_schedule(user_email, agent, token, user_text, answer):
        seen.update(email=user_email, agent=agent["id"], text=user_text,
                    answer=answer)

    monkeypatch.setattr(agent_memory, "schedule_reflection", fake_schedule)
    await rt._run_turn("o@example.com", "agent-1", [
        {"role": "system", "content": "identity"},
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "user", "content": "Set the digest to 7am Manila from now on."}])
    assert seen == {"email": "o@example.com", "agent": "agent-1",
                    "text": "Set the digest to 7am Manila from now on.",
                    "answer": "Done, 7am it is."}


async def test_resume_turn_schedules_no_reflection(monkeypatch):
    """The resume half carries no new message from the person. Reflecting on
    it would write down the same exchange twice, under the tool result
    rather than under what was asked."""
    called = []

    async def fake_chat(**kwargs):
        return "Sent it.", []

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {}, "meta": {"toolIds": [], "access": "all"}}
    await _wire_turn(monkeypatch, row, fake_chat)
    monkeypatch.setattr(agent_memory, "schedule_reflection",
                        lambda *a, **k: called.append(a))

    await rt._resume_turn(
        "o@example.com", "agent-1",
        [{"role": "user",
          "content": "Send the digest at 7am Manila from now on, please."}],
        [], True)
    assert called == []


async def test_a_turn_that_stopped_to_ask_schedules_no_reflection(monkeypatch):
    """Nothing is settled yet: the owner has not answered. Writing it down
    here would record a thing the agent was stopped from doing as a thing it
    did."""
    called = []

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(
            [{"role": "assistant", "content": "", "tool_calls": []}],
            [{"id": "c1", "function": {"name": "send_email"}}])

    row = {"id": "agent-1", "name": "Ada", "base_model_id": "x:free",
           "params": {}, "meta": {"toolIds": [], "access": "ask"}}
    await _wire_turn(monkeypatch, row, fake_chat)
    monkeypatch.setattr(agent_memory, "schedule_reflection",
                        lambda *a, **k: called.append(a))

    out = await rt._run_turn(
        "o@example.com", "agent-1",
        [{"role": "user",
          "content": "Send the digest at 7am Manila from now on, please."}])
    assert "pending" in out
    assert called == []
