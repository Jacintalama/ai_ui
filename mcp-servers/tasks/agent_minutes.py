"""Minutes of a team meeting (2026-10-26).

A meeting is more than one agent answering the same message
(routes_agent_chat._run_round). Until now it ended and the decisions
scrolled away in the chat. Now, once the last agent has spoken, the agent
that spoke first takes the minutes: what was Decided, what is To do and by
whom, and the Open questions, in one bubble under the answers. Each To do
line becomes a real row in tasks.items, which is what the office's To do
list draws, so the meeting leaves work behind. The bubble is announced like
any answer (speaking_started), so a speaker that is on reads it aloud.

The minutes are asked of the base model as the person (routes_agent_turn
._answer_as_io), with the question and every answer, and the reply is
JSON. Anything that is not JSON, or that says nothing, is no minutes: a
meeting must never fail because its minutes could not be taken.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("agent_minutes")

#: Minutes need something to minute: one answer is a reply, not a meeting.
MIN_ANSWERS = 2
#: Caps on what one meeting may leave behind, whatever the model says.
MAX_LINES = 8
MAX_LINE_CHARS = 200
#: How much of the meeting the minute-taker reads. A long answer is cut,
#: not dropped: the gist is at the start.
MAX_ANSWER_CHARS = 2500

LABEL = "Minutes"
YOU = "You"

SYSTEM = (
    "You take the minutes of a short meeting between a person and their AI "
    "agents. Read the person's question and every agent's answer. Reply with "
    "JSON only, no prose, no code fence, in exactly this shape:\n"
    '{"decided": ["..."], "todo": [{"what": "...", "who": "Name"}], '
    '"open": ["..."]}\n'
    "decided: what was settled or agreed, as short plain sentences. "
    "todo: concrete next actions that somebody said they would do or that "
    "were asked for; who is the agent's name exactly as given, or \"You\" "
    "for the person. open: questions nobody answered or that were left to "
    "the person. Leave a list empty rather than inventing. At most eight "
    "lines per list. No long dashes."
)


def prompt(question: str, answers: list[tuple[str, str]], names: list[str]) -> list[dict]:
    """The messages the minute-taker reads."""
    lines = [f"Agents in the meeting: {', '.join(names) or 'none'}", "",
             f"The person asked: {question.strip() or '(nothing)'}", "", "Answers:"]
    for name, text in answers:
        lines.append(f"{name}: {(text or '').strip()[:MAX_ANSWER_CHARS]}")
    lines += ["", "Reply with the JSON only."]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(lines)}]


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def _line(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:MAX_LINE_CHARS]


def parse(text: str, names: list[str]) -> dict | None:
    """The minutes in `text`, cleaned, or None when there are none.

    Takes the first {...} in the reply, so a model that adds a word before
    or after still counts. Every line is one line; a to-do names an agent
    from `names` or You; empty lists are kept empty; nothing at all is
    None."""
    raw = _FENCE.sub("", text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    known = {n.lower(): n for n in names}

    def strings(key):
        v = data.get(key)
        return [_line(x) for x in v if _line(x)][:MAX_LINES] if isinstance(v, list) else []

    todo = []
    for item in data.get("todo") or []:
        if isinstance(item, str):
            what, who = _line(item), YOU
        elif isinstance(item, dict):
            what, who = _line(item.get("what")), _line(item.get("who")) or YOU
        else:
            continue
        if not what:
            continue
        who = known.get(who.lower(), YOU if who.lower() in ("you", "me", "the person", "person", "user") else who)
        if who not in known.values() and who != YOU:
            who = YOU
        todo.append({"what": what, "who": who})
        if len(todo) >= MAX_LINES:
            break
    out = {"decided": strings("decided"), "todo": todo, "open": strings("open")}
    return out if (out["decided"] or out["todo"] or out["open"]) else None


def markdown(minutes: dict, when: datetime | None = None) -> str:
    """The bubble: a heading with the day, then the sections that have
    anything in them."""
    when = when or datetime.now(timezone.utc)
    parts = [f"**Minutes, {when.day} {when.strftime('%b')}**"]
    if minutes.get("decided"):
        parts.append("**Decided**\n" + "\n".join(f"- {x}" for x in minutes["decided"]))
    if minutes.get("todo"):
        parts.append("**To do**\n" + "\n".join(f"- {t['who']}: {t['what']}" for t in minutes["todo"]))
    if minutes.get("open"):
        parts.append("**Open questions**\n" + "\n".join(f"- {x}" for x in minutes["open"]))
    return "\n\n".join(parts)


# --- the calls out ---------------------------------------------------------

async def _ask_model(email: str, messages: list[dict]) -> str:
    # Imported here: routes_agent_turn imports a great deal, and this module
    # is read by the chat round, which it also imports.
    from routes_agent_turn import _answer_as_io
    return await _answer_as_io(email, messages)


async def _write_todo_rows(email: str, todo: list[dict]) -> int:
    """One tasks.items row per to-do, for this person, pending. The office's
    To do list (agent_todo) reads exactly these."""
    from db import session
    from models import TaskItem
    meeting_id = uuid.uuid4()
    async with session() as s:
        for t in todo:
            s.add(TaskItem(meeting_id=meeting_id, action_type="MEETING",
                           assignee_name=t["who"], assignee_email=email,
                           description=t["what"], priority="IMPORTANT", status="pending"))
        await s.commit()
    return len(todo)


#: Seams. Tests replace these rather than calling a model or a database.
_ask = _ask_model
_write_todos = _write_todo_rows


async def take(email: str, question: str, answers: list[tuple[str, str]],
               names: list[str], when: datetime | None = None) -> dict | None:
    """The minutes of one meeting, or None. Never raises.

    Returns {"text": markdown, "todo": [...], "written": n} when there is
    something to say. The to-do rows are written here, best effort: minutes
    whose rows could not be written are still minutes, and say so in the
    log rather than to the person."""
    if len([a for a in answers if (a[1] or "").strip()]) < MIN_ANSWERS:
        return None
    try:
        reply = await _ask(email, prompt(question, answers, names))
    except Exception:                                       # noqa: BLE001
        logger.warning("minutes: the model call failed", exc_info=True)
        return None
    minutes = parse(reply, names)
    if not minutes:
        return None
    written = 0
    if minutes["todo"]:
        try:
            written = await _write_todos(email, minutes["todo"])
        except Exception:                                   # noqa: BLE001
            logger.warning("minutes: the to-do rows could not be written", exc_info=True)
    return {"text": markdown(minutes, when), "todo": minutes["todo"], "written": written,
            "minutes": minutes}
