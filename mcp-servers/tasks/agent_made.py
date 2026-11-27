"""Was an agent really made this turn? The service decides, not the model.

Live 2026-11-27: "yes, create Wren" ran create_agent five times, every call
a preview, and the reply said "Wren is created." Nothing was. The same
happened on 2026-10-29 ("Crane is now active"). ``agent_tools.execute_tool_call``
calls ``note`` for every tool call; the main chat route opens
``collecting()`` per request and passes the answer through ``checked``.
Pure decisions, no I/O, and nothing here raises.
"""
from __future__ import annotations

import contextlib
import contextvars
import re

import agent_activity

_TOOL = "create_agent"
_MADE = "Made "
_PREVIEW = "Here is the agent I would create."

_seen: contextvars.ContextVar = contextvars.ContextVar("agent_made_seen",
                                                        default=None)

#: Words that say an agent exists now.
_CLAIM = re.compile(
    r"\b(?:is|has been|was)\s+(?:now\s+)?(?:created|made)\b"
    r"|\bI(?:'ve| have)?\s+(?:just\s+)?(?:created|made)\b", re.I)
#: In the same sentence, these make it a promise or a denial, not a claim.
_NOT_YET = re.compile(r"\b(?:not|nothing|yet|once|when|after|will|until|if)\b"
                      r"|n't\b|n’t\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CODE_LINE = re.compile(r"\n*\(confirm code: [^)]*\)\s*$")
_NAME = re.compile(r"^Name: *(.+)$", re.M)


def _named(tool) -> bool:
    return isinstance(tool, str) and (tool == _TOOL or tool.endswith("_" + _TOOL))


@contextlib.contextmanager
def collecting():
    """Open a fresh list for this request; ``note`` appends to it."""
    seen: list = []
    token = _seen.set(seen)
    try:
        yield seen
    finally:
        _seen.reset(token)


def note(tool, status, result) -> None:
    """Record what one create_agent call did: "made", "preview" or nothing."""
    try:
        seen = _seen.get()
        if seen is None or not _named(tool) or status != agent_activity.STEP_OK:
            return
        text = result if isinstance(result, str) else ""
        if text.startswith(_MADE):
            seen.append(("made", text))
        elif text.startswith(_PREVIEW):
            seen.append(("preview", text))
    except Exception:
        pass


def claims_made(answer) -> bool:
    """True when some sentence of `answer` says an agent was made."""
    if not isinstance(answer, str):
        return False
    return any(_CLAIM.search(s) and not _NOT_YET.search(s)
               for s in _SENTENCE.split(answer))


def checked(answer, seen):
    """`answer`, or, when this turn only previewed an agent and the answer
    says one was made, the service's own last preview under a line saying
    it is not made yet. Anything unexpected comes back as it came."""
    try:
        if not isinstance(answer, str) or not seen:
            return answer
        kinds = [k for k, _ in seen]
        if "made" in kinds or "preview" not in kinds or not claims_made(answer):
            return answer
        preview = [t for k, t in seen if k == "preview"][-1]
        name = _NAME.search(preview)
        who = name.group(1).strip() if name else "The agent"
        body = _CODE_LINE.sub("", preview).strip()
        body = body.replace(_PREVIEW + " Nothing has been made yet.", "").strip()
        return ("%s is not made yet. Here is what it would be:\n\n%s"
                % (who, body))
    except Exception:
        return answer
