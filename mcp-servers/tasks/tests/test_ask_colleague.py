"""One agent asking another.

The tool is intercepted by name before the native-source path, so the guards
live here in trusted code rather than in a row that is editable from the web
UI. `_run_colleague_turn` is a module-level seam so these tests never run a
real turn, following the pattern in tests/test_autofix_loop.py.
"""
import agent_activity
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
    async with agent_handoff.entered("agent-a", "agent-b"):
        async with agent_handoff.entered("agent-b", "agent-c"):
            said = await agent_tools.run_handoff(
                "agent-c", "me@example.com", "Iris", "hello")
    assert ran == []
    assert "too many" in said


async def test_both_agents_are_on_the_stack_while_it_answers(monkeypatch):
    """So a colleague that asks back up the chain is refused rather than
    looping. The CALLER has to be on there, not only the colleague: with
    only ("agent-iris",) on the stack, Iris asking Nora back found Nora
    absent and was allowed."""
    seen = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        seen.append(agent_handoff.stack())
        return "done"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "hello")
    assert seen == [("agent-nora", "agent-iris")]


async def test_nora_iris_nora_is_refused_on_the_real_path(monkeypatch):
    """The design's own named example, driven the way a turn drives it.

    Not by hand-entering both agents on the stack, which is how the first
    version of this test passed while the code was broken: run_handoff pushed
    only the TARGET, so nothing on the real path ever put Nora on the stack
    and Iris asking her back was allowed. Two nested run_handoff calls is the
    only shape that proves it.
    """
    asked = []
    inner = {}

    async def iris_answers(user_email, agent_id, question, parent_run_id=None):
        asked.append(agent_id)
        # Iris, mid-turn, asks the agent that is waiting on her.
        inner["said"] = await agent_tools.run_handoff(
            "agent-iris", user_email, "Nora", "what was the question again")
        return "I asked Nora back and got: " + inner["said"]

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", iris_answers)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora", "Iris"))

    out = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "where is the spec")

    assert asked == ["agent-iris"], "Nora re-entered inside her own turn"
    assert "already" in inner["said"], inner["said"]
    assert "circle" in inner["said"]
    assert out, "the outer handoff still has to answer"


async def test_three_deep_is_refused_on_the_real_path(monkeypatch):
    """Nora -> Iris -> Kai is the cap, so Kai asking a fourth is refused.
    Driven through nested run_handoff calls for the same reason as above.

    No began() here, so the per-turn budget is not open and spend() is a
    no-op: this pins the DEPTH arm of refusal() specifically, not the breadth
    one. refusal() checks depth before breadth anyway, so a real turn refuses
    the same hop for the same reason.
    """
    asked = []
    inner = {}

    async def answers(user_email, agent_id, question, parent_run_id=None):
        asked.append(agent_id)
        if agent_id == "agent-iris":
            return await agent_tools.run_handoff(
                "agent-iris", user_email, "Kai", "and the schema")
        if agent_id == "agent-kai":
            inner["said"] = await agent_tools.run_handoff(
                "agent-kai", user_email, "Rex", "and the deploy")
            return "as far as I got"
        return "done"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", answers)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora", "Iris", "Kai", "Rex"))

    await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "where is the spec")

    assert asked == ["agent-iris", "agent-kai"], asked
    assert "too many" in inner["said"], inner["said"]


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


async def test_no_declared_tools_cannot_use_it(monkeypatch):
    """Fix review finding 2. allowed_native_tools=None must deny this one
    tool rather than being treated as unscoped: every other native tool has
    a second gate after None (a row still has to exist and declare the
    method), but this branch IS the only gate for ask_colleague, so None
    (no declared tools, or a failure listing them) must not silently mean
    everything is allowed."""
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    out = await agent_tools.execute_tool_call(
        _call(agent="Iris", question="hello"), "me@example.com",
        None, "agent-nora")
    assert ran == []
    assert "not been given" in out.lower() or "was not run" in out.lower()


async def test_an_agent_with_the_tool_can_use_it(monkeypatch):
    """Fix review finding 1/4. allowed_native_tools holds public.tool ROW
    ids (e.g. "colleague"), not the method name ("ask_colleague") --
    _load_native_tool_source proves the distinction: it queries
    `id IN :ids` and matches the method name separately. The grant must be
    checked against agent_tools.HANDOFF_TOOL_ROW, or a properly granted
    agent is refused identically to one that was never granted the tool at
    all, which is exactly why a refusal-only test could not catch it."""
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "The spec is in Drive under Q3."

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    out = await agent_tools.execute_tool_call(
        _call(agent="Iris", question="hello"), "me@example.com",
        [agent_tools.HANDOFF_TOOL_ROW], "agent-nora")
    assert ran == ["agent-iris"]
    assert "Q3" in out


async def test_ask_colleague_is_a_read(monkeypatch):
    """Fix review finding 3. The spec: "Asking is a read, so is_write_call
    is false and nothing interrupts"; the owner's chosen rule is "free to
    hand over, but acting still asks". Left classified as a write (the
    default for any name the verb rule has no opinion on), every handoff
    would stop an ask-level agent for approval before the handoff even
    ran -- the opposite of what was chosen."""
    assert agent_tools.is_write_call(agent_tools.HANDOFF_TOOL, {}) is False


# --- What gets recorded, and it is never read off the sentence ---------------
#
# The design commissions tasks.agent_step to answer "how often a handoff
# happened, how often it ended ok". The status used to be derived from the
# result string by matching the prefix "Refused:", and not one handoff refusal
# starts with that word, so every refusal below was filed as ok and `failed`
# was never written by any path at all. These tests pin each one.


async def test_the_recorded_target_is_the_resolved_id_not_the_prose(monkeypatch):
    """The column joins against agent_run.agent_id, and the table stores no
    prose. A model that puts a sentence in `agent` must not land that sentence
    in the row: what is recorded is what _match_colleague resolved."""
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        return "The spec is in Drive under Q3."

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "iris", "where is the spec",
        outcome=outcome)
    assert outcome.target_agent_id == "agent-iris"
    assert outcome.status == agent_activity.STEP_OK


async def test_an_answer_records_ok(monkeypatch):
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        return "Under Q3."

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.run_handoff("agent-nora", "me@example.com", "Iris",
                                 "q", outcome=outcome)
    assert outcome.status == agent_activity.STEP_OK


async def test_a_colleague_with_nothing_to_add_records_ok(monkeypatch):
    """The handoff worked. An agent that has nothing to say is an answer."""
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        return ""

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.run_handoff("agent-nora", "me@example.com", "Iris",
                                 "q", outcome=outcome)
    assert outcome.status == agent_activity.STEP_OK


async def test_an_unknown_colleague_records_refused_and_no_target(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Somebody Else", "hello",
        outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED
    assert outcome.target_agent_id is None, \
        "a name that resolved to nothing must not be stored as a target"
    assert not said.startswith("Refused:"), \
        "the old prose match would have filed this as ok"


async def test_an_empty_question_records_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.run_handoff("agent-nora", "me@example.com", "Iris",
                                 "   ", outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED
    assert outcome.target_agent_id is None


async def test_asking_yourself_records_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.run_handoff("agent-nora", "me@example.com", "Nora",
                                 "hello", outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED


async def test_a_cycle_records_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora", "Iris"))
    outcome = agent_tools.ToolOutcome()
    async with agent_handoff.entered("agent-nora", "agent-iris"):
        await agent_tools.run_handoff("agent-iris", "me@example.com", "Nora",
                                     "back to you", outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED
    assert outcome.target_agent_id == "agent-nora", \
        "this one DID resolve, so the row can say who was refused"


async def test_too_deep_records_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    async with agent_handoff.entered("agent-a", "agent-b"):
        async with agent_handoff.entered("agent-b", "agent-c"):
            await agent_tools.run_handoff("agent-c", "me@example.com", "Iris",
                                         "hello", outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED


async def test_the_breadth_cap_records_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    async with agent_handoff.began("run-1"):
        agent_handoff.spend()
        agent_handoff.spend()
        await agent_tools.run_handoff("agent-nora", "me@example.com", "Iris",
                                     "hello", outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED


async def test_an_agent_without_the_tool_records_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.execute_tool_call(
        _call(agent="Iris", question="hello"), "me@example.com", ["gdrive"],
        "agent-nora", outcome=outcome)
    assert outcome.status == agent_activity.STEP_REFUSED
    assert outcome.target_agent_id is None


async def test_a_colleague_that_blows_up_records_failed(monkeypatch):
    """`failed` was defined by the migration and the design and written by
    nothing. This is the path that writes it."""
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        raise RuntimeError("the colleague fell over")

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    outcome = agent_tools.ToolOutcome()
    await agent_tools.run_handoff("agent-nora", "me@example.com", "Iris",
                                 "hello", outcome=outcome)
    assert outcome.status == agent_activity.STEP_FAILED
    assert outcome.target_agent_id == "agent-iris"


async def test_recording_is_optional(monkeypatch):
    """Every caller that does not record passes nothing, and the tool still
    runs exactly as before."""
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        return "Under Q3."

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "q")
    assert "Q3" in said


async def test_each_level_records_the_run_that_asked_it(monkeypatch):
    """Finding 2 through the real handoff path, two levels deep.

    The fake colleague turn opens agent_handoff.began for its own run, which
    is what _run_turn does for a real one, so parent_run() sees the same
    thing a real nested turn would. Kai's parent has to be IRIS's run: one
    run id shared by the whole chain made it Nora's.
    """
    parents = {}

    async def answers(user_email, agent_id, question, parent_run_id=None):
        parents[agent_id] = parent_run_id
        async with agent_handoff.began("run-" + agent_id.split("-")[-1]):
            if agent_id == "agent-iris":
                return await agent_tools.run_handoff(
                    "agent-iris", user_email, "Kai", "and the schema")
            return "done"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", answers)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora", "Iris", "Kai"))

    async with agent_handoff.began("run-nora"):
        await agent_tools.run_handoff(
            "agent-nora", "me@example.com", "Iris", "where is the spec")

    assert parents == {"agent-iris": "run-nora", "agent-kai": "run-iris"}, parents
