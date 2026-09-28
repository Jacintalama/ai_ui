"""How far one agent may follow another.

A colleague's turn runs in the same asyncio task as the caller's, because
execute_tool_call exec's a native tool's source in-process rather than going
back out over HTTP. So a ContextVar carries the stack, and nothing has to be
threaded through Open WebUI's native-tool plumbing.

The guard lives here, in trusted code, and NOT in the tool's own Open WebUI
row: that row is editable from the web UI, and a depth cap somebody can edit
away is not a depth cap.

Every refusal is a sentence rather than an exception. execute_tool_call's
whole contract is that it never raises, and an agent that is told "no,
because" can write up what it has instead of the turn dying.
"""
from __future__ import annotations

import contextlib
import contextvars

#: How many agents deep a chain may go. Two: Nora may ask Iris, and Iris may
#: ask one more, and that is the end of it. Each level is a whole extra turn
#: on a box that runs them one at a time.
MAX_DEPTH = 2

#: How many colleagues ONE turn may ask. Depth limits how long a chain gets;
#: this limits how wide it gets. Without it a single agent could call the
#: tool five times and spend five extra turns without ever going two deep.
MAX_PER_TURN = 2

#: Every agent in this chain: the one that asked first, then each agent that
#: was asked. BOTH sides of a handoff go on here -- see entered().
_STACK: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "agent_handoff_stack", default=())

#: How many handoffs are open right now. Counted rather than read off the
#: length of _STACK, because the stack does not push an agent it already
#: holds, so its length is the number of agents involved and not the number
#: of hops.
_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "agent_handoff_depth", default=0)

#: How many handoffs this whole chain has spent. A dict rather than an int
#: because a nested turn must increment the SAME budget its caller is
#: spending, and a ContextVar set in a nested context would not be seen by
#: the outer one.
#:
#: It holds ONLY the budget. The run id used to live in here too, and because
#: the outermost turn was the only one that ever wrote it, every colleague's
#: run pointed at the top of the chain instead of at the run that asked it
#: (review, 2026-09-29). Sharing is right for the budget and wrong for the
#: run, so they are two variables.
_TURN: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "agent_handoff_turn", default=None)

#: The run in flight right now. Set by EVERY turn, nested or not, which is
#: what makes parent_run() answer "the run that asked" rather than "the run
#: at the top of the chain".
_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_handoff_run", default=None)


def stack() -> tuple:
    """Every agent in this chain, the one that asked first first.

    The CALLER is on here as well as the agent it asked. That is the whole
    point: Nora asking Iris and Iris then asking Nora back is the cycle the
    design names by name, and it is only refusable if Nora is on the stack.
    """
    return _STACK.get()


def depth() -> int:
    """How many handoffs are open in this chain."""
    return _DEPTH.get()


@contextlib.asynccontextmanager
async def began(run_id: str | None):
    """Open one turn: the chain's shared budget, and whose run is in flight.

    Two separate concerns, deliberately.

    The BUDGET is opened by the outermost turn only. A colleague's turn runs
    inside its caller's context and must spend the SAME budget, or two agents
    each asking twice would be four turns under a cap of two.

    The RUN is set by every turn, nested included, because a colleague's run
    has to point at the run that ASKED it. One run id for the whole chain
    made Kai's run in Nora -> Iris -> Kai record Nora as its parent, against
    what the design says in as many words: "a colleague's run points at the
    run that asked it".
    """
    budget_token = _TURN.set({"spent": 0}) if _TURN.get() is None else None
    run_token = _RUN.set(run_id)
    try:
        yield
    finally:
        _RUN.reset(run_token)
        if budget_token is not None:
            _TURN.reset(budget_token)


def parent_run() -> str | None:
    """The run that is asking right now, or None outside a turn.

    This is what a colleague's run records as its parent, so two levels deep
    it is the middle run and not the outermost one.
    """
    return _RUN.get()


def spent() -> int:
    t = _TURN.get()
    return int((t or {}).get("spent") or 0)


def spend() -> None:
    """Count one handoff against this turn's budget."""
    t = _TURN.get()
    if t is not None:
        t["spent"] = int(t.get("spent") or 0) + 1


@contextlib.asynccontextmanager
async def entered(caller_id: str, target_id: str):
    """Mark one handoff as in flight for the length of this block.

    BOTH agents go on the stack. Pushing only the target is what let the
    design's own named example through: with only ("agent-iris",) on the
    stack, Iris asking Nora back found Nora absent and was allowed, and Nora
    re-entered nested inside her own paused turn. The test meant to catch
    that hand-entered both agents, which no real call path does, so it passed
    on its own setup rather than on the code (review, 2026-09-29).

    The caller is pushed only when the stack does not hold it already, so a
    chain reads as Nora, Iris, Kai rather than repeating whoever is in the
    middle.

    Reset by token rather than by popping, so an exception on the way out
    cannot leave an agent stuck on the stack for the rest of the request.
    """
    chain = stack()
    if caller_id and caller_id not in chain:
        chain = chain + (caller_id,)
    if target_id:
        chain = chain + (target_id,)
    stack_token = _STACK.set(chain)
    depth_token = _DEPTH.set(depth() + 1)
    try:
        yield
    finally:
        _DEPTH.reset(depth_token)
        _STACK.reset(stack_token)


def refusal(caller_id: str, target_id: str) -> str | None:
    """Why this handoff may not happen, or None when it may.

    Called with the RESOLVED target id, before entered() opens the handoff.
    """
    if caller_id and target_id and caller_id == target_id:
        return ("An agent cannot ask itself, so nothing was asked.")
    if target_id in stack():
        return ("That agent is already waiting on this one, so asking it "
                "back would go round in a circle. Nothing was asked.")
    if depth() >= MAX_DEPTH:
        return ("That would be too many agents deep, so nothing was asked. "
                "Answer with what you have.")
    if spent() >= MAX_PER_TURN:
        return ("This turn has already asked as many colleagues as it may, "
                "so nothing was asked. Answer with what you have.")
    return None
