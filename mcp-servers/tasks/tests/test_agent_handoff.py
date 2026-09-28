"""How deep a handoff may go, and who may not be asked.

A colleague's turn runs in the same asyncio task as the caller's, so a
ContextVar carries the stack without threading a parameter through Open
WebUI's native-tool plumbing.

Every refusal is a sentence, never an exception: execute_tool_call's whole
contract is that it does not raise, and a caller that is told "no, because"
can write up what it has.
"""
import agent_handoff


async def test_nothing_is_on_the_stack_to_begin_with():
    assert agent_handoff.stack() == ()


async def test_entering_puts_the_agent_on_the_stack():
    async with agent_handoff.entered("agent-nora"):
        assert agent_handoff.stack() == ("agent-nora",)


async def test_leaving_takes_it_off_again():
    async with agent_handoff.entered("agent-nora"):
        pass
    assert agent_handoff.stack() == ()


async def test_an_error_still_takes_it_off():
    try:
        async with agent_handoff.entered("agent-nora"):
            raise RuntimeError("the turn blew up")
    except RuntimeError:
        pass
    assert agent_handoff.stack() == ()


async def test_a_first_handoff_is_allowed():
    assert agent_handoff.refusal("agent-nora", "agent-iris") is None


async def test_asking_yourself_is_refused():
    """Review Focus 2. A self-handoff is a cycle of length one, and it is
    what a confused model reaches for first."""
    said = agent_handoff.refusal("agent-nora", "agent-nora")
    assert said and "itself" in said


async def test_asking_back_up_the_stack_is_refused():
    async with agent_handoff.entered("agent-nora"):
        async with agent_handoff.entered("agent-iris"):
            said = agent_handoff.refusal("agent-iris", "agent-nora")
            assert said and "already" in said


async def test_past_the_depth_cap_is_refused():
    async with agent_handoff.entered("agent-a"):
        async with agent_handoff.entered("agent-b"):
            said = agent_handoff.refusal("agent-b", "agent-c")
            assert said and "too many" in said


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


async def test_outside_a_turn_there_is_no_parent():
    assert agent_handoff.parent_run() is None


async def test_a_refusal_reads_as_an_answer_not_an_error():
    """The caller shows this to the owner, so it has to be a sentence they
    can act on rather than a stack trace."""
    said = agent_handoff.refusal("agent-nora", "agent-nora")
    assert said.endswith(".")
    assert said[0].isupper()
