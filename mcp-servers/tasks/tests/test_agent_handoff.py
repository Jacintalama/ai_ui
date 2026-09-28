"""How deep a handoff may go, and who may not be asked.

A colleague's turn runs in the same asyncio task as the caller's, so a
ContextVar carries the stack without threading a parameter through Open
WebUI's native-tool plumbing.

Every refusal is a sentence, never an exception: execute_tool_call's whole
contract is that it does not raise, and a caller that is told "no, because"
can write up what it has.

These are unit tests of the guard itself. The tests that prove the guard
fires on the REAL call path live in test_ask_colleague.py, because a guard
tested only through a hand-built stack passes on its own setup: that is
exactly how the cycle refusal shipped broken.
"""
import agent_handoff


async def test_nothing_is_on_the_stack_to_begin_with():
    assert agent_handoff.stack() == ()
    assert agent_handoff.depth() == 0


async def test_entering_puts_BOTH_agents_on_the_stack():
    """The caller as well as the agent it asked. With only the target on
    there, Iris asking Nora back found Nora absent and was allowed."""
    async with agent_handoff.entered("agent-nora", "agent-iris"):
        assert agent_handoff.stack() == ("agent-nora", "agent-iris")


async def test_leaving_takes_it_off_again():
    async with agent_handoff.entered("agent-nora", "agent-iris"):
        pass
    assert agent_handoff.stack() == ()
    assert agent_handoff.depth() == 0


async def test_an_error_still_takes_it_off():
    try:
        async with agent_handoff.entered("agent-nora", "agent-iris"):
            raise RuntimeError("the turn blew up")
    except RuntimeError:
        pass
    assert agent_handoff.stack() == ()
    assert agent_handoff.depth() == 0


async def test_a_middle_agent_is_not_pushed_twice():
    """Nora asks Iris, Iris asks Kai: three agents in the chain, and Iris
    appears once. Depth is counted rather than read off this length for
    exactly that reason."""
    async with agent_handoff.entered("agent-nora", "agent-iris"):
        async with agent_handoff.entered("agent-iris", "agent-kai"):
            assert agent_handoff.stack() == (
                "agent-nora", "agent-iris", "agent-kai")
            assert agent_handoff.depth() == 2


async def test_a_first_handoff_is_allowed():
    assert agent_handoff.refusal("agent-nora", "agent-iris") is None


async def test_asking_yourself_is_refused():
    """Review Focus 2. A self-handoff is a cycle of length one, and it is
    what a confused model reaches for first."""
    said = agent_handoff.refusal("agent-nora", "agent-nora")
    assert said and "itself" in said


async def test_asking_back_up_the_stack_is_refused():
    """The design's own example: Nora -> Iris -> Nora is refused.

    Hand-entered here only to state the rule. test_ask_colleague.py proves
    the same refusal through two nested run_handoff calls, which is the path
    a real turn takes.
    """
    async with agent_handoff.entered("agent-nora", "agent-iris"):
        said = agent_handoff.refusal("agent-iris", "agent-nora")
        assert said and "already" in said


async def test_past_the_depth_cap_is_refused():
    async with agent_handoff.entered("agent-a", "agent-b"):
        async with agent_handoff.entered("agent-b", "agent-c"):
            said = agent_handoff.refusal("agent-c", "agent-d")
            assert said and "too many" in said


async def test_two_handoffs_deep_is_allowed():
    """The cap is a cap on the third, not on the second. Nora may ask Iris
    and Iris may ask one more."""
    async with agent_handoff.entered("agent-a", "agent-b"):
        assert agent_handoff.refusal("agent-b", "agent-c") is None


async def test_the_cap_is_two():
    assert agent_handoff.MAX_DEPTH == 2


async def test_a_third_handoff_in_one_turn_is_refused():
    """Depth limits how long a chain is. This limits how MANY an agent
    starts: one agent calling the tool five times is five extra turns on a
    box that runs them one at a time, and no chain was ever two deep."""
    async with agent_handoff.began("run-1"):
        agent_handoff.spend()
        agent_handoff.spend()
        said = agent_handoff.refusal("agent-nora", "agent-iris")
    assert said and "already asked" in said


async def test_the_breadth_cap_is_two():
    assert agent_handoff.MAX_PER_TURN == 2


async def test_a_turn_knows_the_run_that_asked():
    async with agent_handoff.began("run-1"):
        assert agent_handoff.parent_run() == "run-1"


async def test_a_nested_turn_is_the_run_that_asked_from_then_on():
    """The run id is per turn, not per chain. At two levels deep the inner
    turn's parent must be the MIDDLE run: storing one run id for the whole
    chain made Kai's run in Nora -> Iris -> Kai record Nora as its parent,
    against the design's "a colleague's run points at the run that asked
    it"."""
    async with agent_handoff.began("run-nora"):
        assert agent_handoff.parent_run() == "run-nora"
        async with agent_handoff.began("run-iris"):
            assert agent_handoff.parent_run() == "run-iris"
        assert agent_handoff.parent_run() == "run-nora"


async def test_the_budget_is_shared_across_nesting():
    """The other half of that split, and it must not regress: two agents each
    asking twice is four turns under a cap of two, so the BUDGET stays
    shared even though the run id no longer is."""
    async with agent_handoff.began("run-nora"):
        agent_handoff.spend()
        async with agent_handoff.began("run-iris"):
            assert agent_handoff.spent() == 1, "a nested turn got a fresh budget"
            agent_handoff.spend()
        assert agent_handoff.spent() == 2, "the nested spend was lost"


async def test_outside_a_turn_there_is_no_parent():
    assert agent_handoff.parent_run() is None


async def test_a_refusal_reads_as_an_answer_not_an_error():
    """The caller shows this to the owner, so it has to be a sentence they
    can act on rather than a stack trace."""
    said = agent_handoff.refusal("agent-nora", "agent-nora")
    assert said.endswith(".")
    assert said[0].isupper()
