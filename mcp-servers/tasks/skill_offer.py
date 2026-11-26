"""What counts as something made, so the chat can offer "Save as your skill".

``agent_tools.execute_tool_call`` calls ``note`` for every tool call; the main
chat route opens ``collecting()`` per request and adds ``LINK`` under the reply
when the list is not empty. Pure decisions, no I/O, and ``note`` never raises.
"""
from __future__ import annotations

import contextlib
import contextvars
import json

import agent_activity

LINK = "[Save as your skill](#aiui-say:save-skill)"

_WORKFLOW_TOOLS = ("create_workflow", "activate_workflow")
_AUTOMATION_TOOL = "create_automation"
_AUTOMATION_MADE = "Made the automation"

_made: contextvars.ContextVar = contextvars.ContextVar("skill_offer_made",
                                                        default=None)


def _named(tool, name: str) -> bool:
    return isinstance(tool, str) and (tool == name or tool.endswith("_" + name))


def counts(tool: str, status: str, result: str) -> bool:
    """True when this call really made a workflow or an automation."""
    try:
        if status != agent_activity.STEP_OK:
            return False
        if any(_named(tool, n) for n in _WORKFLOW_TOOLS):
            data = json.loads(result)
            return isinstance(data, dict) and data.get("ok") is True
        if _named(tool, _AUTOMATION_TOOL):
            return isinstance(result, str) and result.startswith(_AUTOMATION_MADE)
    except Exception:
        return False
    return False


@contextlib.contextmanager
def collecting():
    """Open a fresh list for this request; ``note`` appends to it."""
    made: list = []
    token = _made.set(made)
    try:
        yield made
    finally:
        _made.reset(token)


def note(tool: str, status: str, result: str) -> None:
    try:
        made = _made.get()
        if made is not None and counts(tool, status, result):
            made.append(tool)
    except Exception:
        pass


def with_link(answer: str) -> str:
    if LINK in (answer or ""):
        return answer
    return f"{answer or ''}\n\n{LINK}"
