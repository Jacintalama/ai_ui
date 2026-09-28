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

_STACK: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "agent_handoff_stack", default=())

#: The top-level run everything in this chain hangs off, and how many
#: handoffs it has spent. A one-item list rather than an int because a
#: nested turn must increment the SAME budget its caller is spending, and a
#: ContextVar set in a nested context would not be seen by the outer one.
_TURN: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "agent_handoff_turn", default=None)


def stack() -> tuple:
    """The agents currently waiting on a handoff, outermost first."""
    return _STACK.get()


@contextlib.asynccontextmanager
async def began(run_id: str | None):
    """Open a handoff budget for one top-level turn.

    Only the outermost turn opens one. A colleague's turn runs inside its
    caller's context and must spend the SAME budget, or two agents each
    asking twice would be four turns under a cap of two.
    """
    if _TURN.get() is not None:
        yield
        return
    token = _TURN.set({"run_id": run_id, "spent": 0})
    try:
        yield
    finally:
        _TURN.reset(token)


def parent_run() -> str | None:
    """The run a colleague's run should point at, or None outside a turn."""
    t = _TURN.get()
    return (t or {}).get("run_id")


def spent() -> int:
    t = _TURN.get()
    return int((t or {}).get("spent") or 0)


def spend() -> None:
    """Count one handoff against this turn's budget."""
    t = _TURN.get()
    if t is not None:
        t["spent"] = int(t.get("spent") or 0) + 1


@contextlib.asynccontextmanager
async def entered(agent_id: str):
    """Mark an agent as waiting on a colleague for the length of this block.

    Reset by token rather than by popping, so an exception on the way out
    cannot leave an agent stuck on the stack for the rest of the request.
    """
    token = _STACK.set(stack() + (agent_id,))
    try:
        yield
    finally:
        _STACK.reset(token)


def refusal(caller_id: str, target_id: str) -> str | None:
    """Why this handoff may not happen, or None when it may."""
    if caller_id and target_id and caller_id == target_id:
        return ("An agent cannot ask itself, so nothing was asked.")
    if target_id in stack():
        return ("That agent is already waiting on this one, so asking it "
                "back would go round in a circle. Nothing was asked.")
    if len(stack()) >= MAX_DEPTH:
        return ("That would be too many agents deep, so nothing was asked. "
                "Answer with what you have.")
    if spent() >= MAX_PER_TURN:
        return ("This turn has already asked as many colleagues as it may, "
                "so nothing was asked. Answer with what you have.")
    return None
