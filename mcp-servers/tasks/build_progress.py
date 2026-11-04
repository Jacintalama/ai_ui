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
}


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
