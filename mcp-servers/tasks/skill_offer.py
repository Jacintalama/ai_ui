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

#: What the button sends, word for word. integrations-ui.js holds the same
#: sentence (AIUI_SAY_TEXTS['save-skill'].text); a test reads it from there,
#: so the two cannot drift. The main chat gives the assistant the skills tool
#: when the person's last message is this (is_ask).
ASK = "Write a skill from what you just set up for me, and show it to me before saving."

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


def is_ask(text) -> bool:
    """True when `text` is the button's message, give or take whitespace."""
    return isinstance(text, str) and text.strip() == ASK


def without_link(answer: str) -> str:
    """`answer` with every copy of LINK taken out, and the blank lines
    around it, the rest of the text left as it was.

    The link is in the chat history after one offer, and a model reading it
    back can copy it into a reply where nothing was made. The service owns
    it: the main chat strips the model's copies and adds it only after a
    real write. Text either side of a copy is joined by a blank line when a
    line break was there, by a space when it stood inside a sentence.
    Anything that is not a string comes back as it came.
    """
    if not isinstance(answer, str) or LINK not in answer:
        return answer
    parts = answer.split(LINK)
    out = parts[0]
    for nxt in parts[1:]:
        left, right = out.rstrip(), nxt.lstrip()
        if not left or not right:
            out = left + right
            continue
        gap = out[len(left):] + nxt[:len(nxt) - len(right)]
        out = left + ("\n\n" if "\n" in gap else " ") + right
    return out


def with_link(answer: str) -> str:
    if LINK in (answer or ""):
        return answer
    return f"{answer or ''}\n\n{LINK}"
