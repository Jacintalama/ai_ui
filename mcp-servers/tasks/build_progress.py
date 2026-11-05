"""What a build is doing, in words a person reading a chat would use.

The main chat has watched builds since 2026-11-03 and could only count
minutes at them: "Still building, 4 min so far." That says the thing is
alive and nothing about whether it is nearly done, stuck on a browser
check, or rolling back a change that broke the app.

The build has always known. `routes_execution._run_execution` runs named
steps in order and has since it was written; nothing carried the name out
of the process.

Two rules hold everything here together.

**A step is written for the person who asked, not for us.** "AutoFix pass
2" is our word for it. "Checking the app in a browser and fixing what it
finds" is the same fact in the language of somebody who asked for a
website. The names are therefore not the function names, on purpose, and a
test pins that they stay sentences.

**Saying so must never cost the build.** Every write here fails open. A
build that completes and could not say it reached the docs sweep is a
build that completed; a build that dies because the progress write raised
is a feature costing somebody their work. That is the same rule the commit
sweep and the regression guard already follow.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("build_progress")

#: How much of a step the page is given. The line sits under a reply in a
#: chat, so it is one sentence and not a paragraph.
MAX_STEP_CHARS = 120

#: The steps, in the order _run_execution runs them, in the words the
#: person reading the chat would use. Keys are ours, values are theirs.
STEPS = {
    "baseline": "Checking how the app works now, so a change that breaks it "
                "can be undone",
    "building": "Writing the code",
    "smoke": "Opening the app in a browser to see whether it works",
    "autofix": "Fixing what the browser check found",
    "docs": "Writing the README",
    "commit": "Saving the changes to version history",
    "guard": "The app broke, putting it back the way it was",
    "asking": "Waiting for an answer to a question",
    # The light lane: a simple site, written by one model call rather than
    # by an agent with a workspace. It has no baseline to take, nothing to
    # autofix and no browser to open, so it walks three steps and not six.
    # Showing somebody the agent's six for a build that finishes in under a
    # minute would be a lie told in a progress bar.
    "drafting": "Writing the page",
    "proofing": "Making sure the page is finished and will load",
    "filing": "Saving it to version history",
}


#: The steps a build walks through, in the order _run_execution runs them.
#: Python keeps insertion order, so this IS the order of STEPS above, named
#: here so the fact is asserted rather than assumed by anything reading it.
ORDER = ("baseline", "building", "smoke", "autofix", "docs", "commit")

#: The light lane's walk. A build is on one walk or the other, never both.
LIGHT_ORDER = ("drafting", "proofing", "filing")

#: Which walk a step belongs to. Derived from the step itself, so a task
#: needs no new column to say which lane it is on and there is no
#: migration to get wrong.
AGENT_LANE = "agent"
LIGHT_LANE = "light"


def lane_of(step: str) -> str:
    """The walk this step belongs to. Unknown steps read as the agent's,
    which is the lane every build was on before the light one existed."""
    return LIGHT_LANE if str(step or "") in LIGHT_ORDER else AGENT_LANE


def order_for(lane: str) -> tuple:
    return LIGHT_ORDER if str(lane or "") == LIGHT_LANE else ORDER


def lane_of_name(lane: str) -> str:
    """A lane name, normalised. Anything unrecognised is the agent's,
    which is the walk every build was on before the light one existed, so
    a typo in a query string shows a real list rather than nothing."""
    return LIGHT_LANE if str(lane or "") == LIGHT_LANE else AGENT_LANE

#: Not part of that walk. "guard" means a change broke the app and is being
#: undone; "asking" means the build stopped to ask something. Neither is a
#: stage you pass through on the way to a finished app, and showing them in
#: a list of what is still to come would promise every build a rollback.
OUT_OF_BAND = ("guard", "asking")


def steps_in_order(lane: str = AGENT_LANE) -> list:
    """The walk, for a page that wants to draw all of it at once.

    The wording lives HERE and is served, never copied into a page. There
    are already two places that show a step to somebody (the chat and the
    build view) and a third copy of these sentences would be a third place
    to change and a third to fall out of step.
    """
    return [{"key": k, "said": STEPS[k]}
            for k in order_for(lane) if k in STEPS]


def reached(step: str, lane: str | None = None) -> int:
    """How far along the walk a build is, or -1 when it is not on it.

    -1 for an unknown step and for the two out-of-band ones, so a caller
    can tell "rolling back" from "somewhere in the middle".
    """
    step = str(step or "")
    walk = order_for(lane if lane is not None else lane_of(step))
    try:
        return walk.index(step)
    except ValueError:
        return -1


def wording(step: str) -> str:
    """The sentence for a step key, or the key itself if it is unknown.

    Unknown returns the key rather than "" so a step added in code and
    forgotten here still shows SOMETHING, which is how anybody notices it
    is missing. Silently showing nothing is how it stays missing.
    """
    return (STEPS.get(str(step or ""), str(step or "")) or "")[:MAX_STEP_CHARS]


def line_for(task: dict) -> str:
    """What the chat shows under the reply while a build runs, or "".

    Empty for a build that is not running, so the caller keeps its own
    rules about when to draw anything at all.
    """
    if not isinstance(task, dict):
        return ""
    if str(task.get("status") or "") not in ("running", "planning"):
        return ""
    return wording(task.get("build_step") or "")


# --- writing it down -------------------------------------------------------

async def _write(task_id, step: str) -> None:
    from sqlalchemy import update
    from db import session
    from models import TaskItem
    async with session() as s:
        await s.execute(update(TaskItem).where(TaskItem.id == task_id).values(
            build_step=step[:MAX_STEP_CHARS],
            build_step_at=datetime.now(timezone.utc)))
        await s.commit()


_write_seam = _write


async def say(task_id, step: str) -> None:
    """Record which step this build is on. NEVER raises.

    A build that completes and could not say it reached the docs sweep is
    a build that completed. A build that dies because this raised is a
    progress line costing somebody their work, which is the trade this
    codebase has already decided twice: every step after the agent fails
    open, on purpose.
    """
    if task_id is None or not str(step or "").strip():
        return
    try:
        await _write_seam(task_id, str(step))
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the build step", exc_info=True)
