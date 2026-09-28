"""One agent asking another.

The tool is intercepted by name before the native-source path, so the guards
live here in trusted code rather than in a row that is editable from the web
UI. `_run_colleague_turn` is a module-level seam so these tests never run a
real turn, following the pattern in tests/test_autofix_loop.py.
"""
import agent_handoff
import agent_tools


def _call(name="ask_colleague", **args):
    import json
    return {"id": "call-1", "function": {"name": name,
                                         "arguments": json.dumps(args)}}


def _roster(*names):
    return [{"id": "agent-" + n.lower(), "name": n} for n in names]


async def test_the_colleague_is_asked_and_the_answer_comes_back(monkeypatch):
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        return "The spec is in Drive under Q3."

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "where is the spec")
    assert "Q3" in said
    assert "Iris" in said


async def test_an_agent_that_is_not_yours_is_refused(monkeypatch):
    """Review Focus 1. The id comes off a model, so it is never trusted."""
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Somebody Else", "hello")
    assert ran == []
    assert "no colleague" in said.lower()


async def test_asking_yourself_never_runs_a_turn(monkeypatch):
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Nora", "hello")
    assert ran == []
    assert "itself" in said


async def test_too_deep_never_runs_a_turn(monkeypatch):
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    async with agent_handoff.entered("agent-a"):
        async with agent_handoff.entered("agent-b"):
            said = await agent_tools.run_handoff(
                "agent-b", "me@example.com", "Iris", "hello")
    assert ran == []
    assert "too many" in said


async def test_the_colleague_is_on_the_stack_while_it_answers(monkeypatch):
    """So a colleague that asks back up the chain is refused by Task 2's
    guard rather than looping."""
    seen = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        seen.append(agent_handoff.stack())
        return "done"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "hello")
    assert seen == [("agent-iris",)]


async def test_a_turn_that_blows_up_is_still_an_answer(monkeypatch):
    """execute_tool_call never raises, so neither does this."""
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        raise RuntimeError("the colleague fell over")

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "hello")
    assert "could not" in said.lower()


async def test_an_empty_question_is_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "   ")
    assert "nothing to ask" in said.lower()


async def test_the_tool_is_named():
    assert agent_tools.HANDOFF_TOOL == "ask_colleague"


async def test_an_agent_without_the_tool_cannot_use_it(monkeypatch):
    """Review Focus 3. tool_ids scoping still applies: interception must not
    become a back door around the grant."""
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    out = await agent_tools.execute_tool_call(
        _call(agent="Iris", question="hello"), "me@example.com",
        ["gdrive"], "agent-nora")
    assert ran == []
    assert "not been given" in out.lower() or "was not run" in out.lower()
