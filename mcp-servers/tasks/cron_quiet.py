"""Which cron outputs ring the red number, and which arrive already read.

The Cron Outputs page is an inbox (migration 072) and the red number on Cron
Jobs in the sidebar is how many outputs are unread. On 2026-11-24 it said 5
and none of the 5 needed anything: three Inbox checks that each began
"Important first: none. Nothing that needs a reply from you", a daily quote
and a morning brief. A number that rings for nothing is a number people learn
to ignore, so two things now decide whether a new output counts:

  - QUIET RUNS. The agent that wrote the answer is the one that read the mail
    or the board, so it is asked to say when nothing in it needs the person
    (ASK, added to the brief on the schedule surface only). It says so with
    MARK on a line of its own; the mark is taken out before anything is
    stored or delivered, and the output arrives read. It is still in the
    inbox, only not counted.
  - THE PER-CRON SWITCH, `tasks.schedules.notify` (migration 073). A muted
    cron's outputs always arrive read.

FAIL LOUD, NEVER QUIET. Leaving the mark out is the safe mistake: the output
counts, exactly as it did before this existed, so the ask tells the model to
leave it out when unsure. And a run that did not complete always counts,
muted or quiet or not, because a cron that broke is the one thing the owner
has to hear about.

Pure, no I/O, so all of it is tested without an agent or a database.
"""
import re

#: Written by the agent on a line of its own. Unlikely in real prose, and
#: easy to find with the formatting a model sometimes wraps it in.
MARK = "[[nothing-needs-you]]"

ASK = (
    "This is a scheduled run and its answer lands in the person's Cron "
    "Outputs inbox. When you have written the answer, decide one more thing. "
    "If NOTHING in it needs the person to reply, decide, fix or do anything "
    "(for example no important email, nothing failing, nothing new to act "
    "on), add one last line that is exactly " + MARK + " and nothing else. "
    "If anything in it does need them, or you are not sure, leave that line "
    "out. Never mention this line or explain it."
)

# The mark alone on a line, allowing the wrappers models add: backticks,
# bold, a bullet or quote marker, trailing punctuation.
_MARK_LINE = re.compile(
    r"^[ \t>*_`\-]*" + re.escape(MARK) + r"[ \t*_`.]*$",
    re.IGNORECASE | re.MULTILINE,
)


def split(result: str | None) -> tuple[str | None, bool]:
    """(the answer without the mark, whether the agent marked it quiet).

    Only a mark on a line of its own counts. A mark inside a sentence is the
    model talking ABOUT the mark, which is not the same as using it, so that
    text is kept as it is and the output counts.
    """
    if not result:
        return result, False
    if not _MARK_LINE.search(result):
        return result, False
    cleaned = _MARK_LINE.sub("", result)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, True


def arrives_unread(status: str, quiet: bool, notify) -> bool:
    """Whether a new output counts in the red number.

    `notify` is the schedule's switch; None (a row from before migration
    073, or a test double without the attribute) counts as on.
    """
    if str(status) != "completed":
        return True
    if notify is False:
        return False
    return not quiet
