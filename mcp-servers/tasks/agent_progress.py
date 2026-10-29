"""What is happening right now, said while it is still happening.

The main chat went quiet for the length of a turn. Measured 2026-10-29 on
the live box: 2.4s for a question the free model answers, 9.5s for "check my
inbox", 12.3s for a message with an attachment that an agent took, against a
120s timeout, and recorded turns average 5.6s and reach 41.7s. For all of
that the person saw a spinner and nothing else, because the one status line
there used to be was removed on 2026-10-28, rightly: it said "Choosing who
answers..." on every message including the ones where nothing was being
chosen, so it made an ordinary wait look like a decision.

The fix is not to put that line back. It is to say only things that are
true of THIS message, and only once they are known: who is answering,
because an agent was named or Jev picked one, and what is being read,
because Jev picked a tool for it. A message the free model answers says
nothing at all, which is correct, because nothing is happening to it.

**This reports, it does not stream the answer.** That is deliberate and not
a shortcut: `agent_jev.reply_answers` can decide an agent's reply did not
answer the question, in which case it is discarded and the free model
answers instead (`_jev_answer`), and `_assistant_failed` does the same for
the assistant. Text that may still be thrown away must not already be on
the person's screen. The plain free-model path, which is the fast one, has
always streamed and still does.

Nothing here can break a turn. `say` swallows everything, and with nobody
listening it does nothing at all, which is the case for Discord, the panel
and every test that does not opt in.
"""
import contextlib
import contextvars
import logging

logger = logging.getLogger(__name__)

#: How a tool is named to the person whose account it is about to read.
#: Deliberately shorter and more concrete than agent_jev.TOOL_NOTES, which
#: is prose written to help Jev decide ("reading, searching, drafting or
#: sending the person's email"). This is a thing on a status line, so it has
#: to fit and to read as a place rather than a capability.
TOOL_LABELS = {
    "gmail": "your email",
    "calendar": "your calendar",
    "gdrive": "your Drive",
    "documents": "your documents",
    "excel_creator": "a spreadsheet",
    "executive_dashboard": "your numbers",
    "code": "your apps",
    "account": "your account",
    "schedules": "your schedules",
    "remember": "what you asked me to remember",
    "skills": "your skills",
    "video": "video",
    "colleague": "your agents",
    "agents": "your agents",
    "agent_builder": "your agents",
    "automations": "your automations",
    "server:mcp-proxy": "the web",
}


def label_for(tool: str) -> str:
    """What to call one tool. Falls back to the id, which is ugly but true,
    and is better than silently dropping a tool from the line: the point of
    the line is that the person can see what was touched."""
    return TOOL_LABELS.get(tool) or str(tool)


def _join(labels: list) -> str:
    """"a", "a and b", "a, b and c". Deduped, order kept, because Jev can
    pick two tools that read the same place to a person (agents/colleague
    are both "your agents") and "your agents and your agents" is nonsense.
    """
    seen = []
    for name in labels:
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]
    return ", ".join(seen[:-1]) + " and " + seen[-1]


def places(tools) -> str:
    """The places a list of tool ids will read, as one phrase."""
    return _join([label_for(t) for t in (tools or [])])


def reading_line(tools) -> str:
    """The line said while the assistant's turn runs. Empty for no tools,
    which is the message the free model answers and should stay silent."""
    where = places(tools)
    return ("Reading %s..." % where) if where else ""


def used_line(tools) -> str:
    """The line left behind afterwards, so a grounded answer does not look
    like a guess. Before this, an answer built from the person's own mailbox
    was indistinguishable on screen from one the model invented."""
    where = places(tools)
    return ("Used %s" % where) if where else ""


def _names(names) -> str:
    return _join([str(n) for n in (names or []) if n])


def answering_line(names) -> str:
    """Who is about to speak. Only ever real agent names: the assistant is
    not an agent and must never be announced as one (2026-10-28, after a
    general-knowledge question came back under "Answered by your agent"
    with no agent involved)."""
    who = _names(names)
    return ("%s is answering..." % who) if who else ""


def answered_by(names) -> str:
    """The line left on screen once real agents have spoken. Empty for
    none, so neither the assistant nor the free model can borrow an
    agent's credit."""
    who = _names(names)
    return ("Answered by %s" % who) if who else ""


#: Who, if anyone, is listening. A ContextVar because the route knows and
#: the places that learn something are several frames down, the same shape
#: as agent_activity's meeting and job marks.
_REPORT: contextvars.ContextVar = contextvars.ContextVar(
    "agent_progress_report", default=None)


@contextlib.contextmanager
def reporting_to(report):
    """Send every `say` inside this block to `report`, a plain callable
    taking one string. It must not block or raise; pushing onto a queue is
    what the SSE route does."""
    token = _REPORT.set(report)
    try:
        yield
    finally:
        _REPORT.reset(token)


def listening() -> bool:
    """Whether anybody will hear a `say`. Worth checking before building a
    line that costs anything; the lines here cost nothing, so most callers
    do not bother."""
    return _REPORT.get() is not None


def say(line: str) -> None:
    """Say one thing, if anybody is listening. Never raises.

    A turn must never fail because a status line could not be delivered,
    which is the whole reason this swallows rather than propagates: the
    answer is the point and this is decoration on top of it.
    """
    report = _REPORT.get()
    if report is None or not line:
        return
    try:
        report(line)
    except Exception:                                       # noqa: BLE001
        logger.debug("a progress line could not be delivered", exc_info=True)
