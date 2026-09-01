"""Stopping to ask the owner before an agent changes anything.

The tool loop runs inside one request and cannot sit and wait, so an agent on
"With access" ends its turn early and picks it back up on the next inbound
message. This module holds the three small decisions that go with that: what
counts as an answer, what the question looks like, and where the held turn is
kept.

Nothing here talks to a service. That keeps it testable without a pipeline,
which matters because the verdict matcher is the piece most likely to be
wrong in a way that only shows up on somebody's real sentence.
"""
import json

#: Long enough to walk away and come back, short enough that an approval
#: cannot be answered days later against a conversation nobody remembers.
PENDING_TTL_SECONDS = 600

#: One argument value, in the question. Enough to recognise an email address
#: or a subject line, not enough for a message body to bury the question.
MAX_ARG_CHARS = 120

#: How many arguments of one call are shown. Beyond this the question stops
#: being readable, which is the same as not asking.
MAX_ARGS_SHOWN = 5

DROPPED = "I dropped the action I was waiting on."
NOT_YOURS = ("That was not your agent's question to answer, so I left it "
             "alone.")
EXPIRED = ("I am not waiting on anything now. Ask again and I will run it "
           "from the top.")

_YES = frozenset({"yes", "y", "ok", "okay", "sure", "go ahead", "do it",
                  "approve", "approved", "yep", "yeah", "please do"})
_NO = frozenset({"no", "n", "stop", "cancel", "dont", "don't", "nope",
                 "no thanks", "leave it"})


def pending_key(platform: str, chat_id: str) -> str:
    return "agentpending:%s:%s" % (platform, chat_id)


def verdict(text: str) -> bool | None:
    """True for yes, False for no, None for anything else.

    Matched on the WHOLE message, not on words inside it. "nothing has
    changed" contains "no" and is not a refusal, and reading it as one would
    silently cancel something the person never mentioned.

    None is not a failure. Anything that is not a verdict drops the held
    action and is handled as an ordinary message, because being trapped in a
    confirmation loop is the failure mode people hate most.
    """
    cleaned = (text or "").strip().lower().rstrip(".!")
    if not cleaned:
        return None
    if cleaned in _YES:
        return True
    if cleaned in _NO:
        return False
    return None


def _arguments(fn: dict) -> dict:
    raw = fn.get("arguments")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (ValueError, TypeError):
        # Comes from a model, so the wrong type is exactly what to expect.
        return {}
    return parsed if isinstance(parsed, dict) else {}


def prompt(agent_name: str, calls: list) -> str:
    """The question, in the agent's own terms.

    The tool's own name and its arguments, not a hand-written phrase per
    tool. A phrasebook covering the 300+ proxy tools would be wrong
    somewhere, and where it was wrong is exactly where somebody would approve
    the wrong thing.
    """
    lines = ["%s wants to run:" % (agent_name or "This agent")]
    for call in calls or []:
        call = call if isinstance(call, dict) else {}
        fn = call.get("function")
        fn = fn if isinstance(fn, dict) else {}
        name = fn.get("name")
        name = name.strip() if isinstance(name, str) and name.strip() else "an unnamed tool"
        lines.append("  " + name)
        for key, value in list(_arguments(fn).items())[:MAX_ARGS_SHOWN]:
            lines.append("     %s: %s" % (key, str(value)[:MAX_ARG_CHARS]))
    if len(lines) == 1:
        # Every call was unreadable. Still ask: acting without asking is the
        # one thing this level exists to prevent.
        lines.append("  something it did not name")
    lines.append("")
    lines.append("Reply yes to let it, or no to skip.")
    return "\n".join(lines)
