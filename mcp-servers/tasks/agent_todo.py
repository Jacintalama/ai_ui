"""What the office still has to do, read from the work already recorded.

`tasks.items` has held this since migration 001: a description, who it is
for, how urgent it is, and where it has got to. Nothing on the agents
surface has ever shown it, so the one place that says what the team is
doing was the live activity feed, which only says what happened in the last
few minutes and forgets a job the moment it ends.

Nothing here invents a task. A line on this list is a row somebody or
something really wrote, which is the same rule the floor follows: draw what
is there.
"""
import logging

from sqlalchemy import text as sql_text

from db import session

logger = logging.getLogger(__name__)

#: Still to do, in the order a person would work them. `awaiting_input` is
#: open rather than done: it is a job stopped on a question, which is the
#: most urgent kind there is, so it sorts first.
OPEN_STATUSES = ("awaiting_input", "running", "claimed_manual", "pending")

#: How many lines the panel is given. The list is a prompt to act, not an
#: archive: past this it stops being readable and the history page is the
#: right place to look instead.
MAX_OPEN = 8
MAX_DONE = 3


def _shape(row) -> dict:
    """One line, as the panel reads it."""
    return {
        "id": str(row["id"]),
        "what": row["description"] or "",
        "who": row["assignee_name"] or "",
        "priority": (row["priority"] or "").lower(),
        "status": row["status"] or "",
        "kind": (row["action_type"] or "").lower(),
        "at": (row["completed_at"] or row["created_at"]).isoformat()
              if (row["completed_at"] or row["created_at"]) else None,
    }


async def todo_for(user_email: str) -> dict:
    """This person's open work, and the few things just finished.

    Scoped to the caller, like every other per-user read here. Fails soft:
    a panel that cannot load its list must not take the office down with
    it, so an error is an empty list and a logged warning.
    """
    if not user_email:
        return {"open": [], "done": []}
    try:
        async with session() as s:
            rows = (await s.execute(
                sql_text(
                    # Open first, each status in the order above, then the
                    # most urgent, then oldest: a critical job that has been
                    # waiting since Monday belongs at the top.
                    "SELECT id, description, assignee_name, priority, status,"
                    "       action_type, created_at, completed_at "
                    "FROM tasks.items "
                    "WHERE assignee_email = :e AND status = ANY(:open) "
                    "ORDER BY array_position(:open, status), "
                    "  CASE priority WHEN 'CRITICAL' THEN 0 "
                    "                WHEN 'IMPORTANT' THEN 1 ELSE 2 END, "
                    "  created_at "
                    "LIMIT :n"),
                {"e": user_email, "open": list(OPEN_STATUSES),
                 "n": MAX_OPEN})).mappings().all()
            done = (await s.execute(
                sql_text(
                    "SELECT id, description, assignee_name, priority, status,"
                    "       action_type, created_at, completed_at "
                    "FROM tasks.items "
                    "WHERE assignee_email = :e AND status = 'completed' "
                    "ORDER BY completed_at DESC NULLS LAST "
                    "LIMIT :n"),
                {"e": user_email, "n": MAX_DONE})).mappings().all()
    except Exception:                                      # noqa: BLE001
        logger.warning("the to-do list could not be read", exc_info=True)
        return {"open": [], "done": []}
    return {"open": [_shape(r) for r in rows],
            "done": [_shape(r) for r in done]}
