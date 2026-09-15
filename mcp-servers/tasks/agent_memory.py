"""What an agent remembers between conversations: its subconscious.

Two stores. The agent's own notes live in tasks.agent_memory, one row per
(agent, person, note). Facts about the person live in Open WebUI's
public.memory, because that is the table Settings > Personalization >
Memories and the Brain graph already read, and a fact every agent shares
belongs where the person can see and delete it.

Two directions. Recall: recall_block() renders both stores as one block of
text that the identity line (chat, panel, bots) and the schedule runner
carry, so every turn on every surface starts from what is known. Capture:
schedule_reflection() runs a detached completion after a chat turn that
writes down what was settled, so the agent does not have to think to
remember. The remember tool still exists for when the person says
"remember this".

Everything here fails open. A turn must never fail because its memory did.
"""
import asyncio
import json
import logging
import re
import time
import uuid

from sqlalchemy import text as sql_text

from db import session

logger = logging.getLogger(__name__)

#: The whole block, notes plus facts. Sized so it costs less than the skill
#: brief and far less than the conversation it rides in front of.
RECALL_BUDGET_CHARS = 2400
NOTES_BUDGET_CHARS = 1400
FACTS_BUDGET_CHARS = 1000

#: Caps on what is kept. Beyond these the oldest by last_seen_at goes.
MAX_NOTES_PER_AGENT = 60
MAX_FACTS_PER_PERSON = 100

#: The reflection's own limits. Three of each per turn is plenty: a turn
#: that settled more than three things is rare, and a model told it may
#: write ten writes ten.
MAX_ITEMS_PER_KIND = 3
MAX_ITEM_CHARS = 200
MIN_ITEM_CHARS = 12

#: A turn worth reflecting on. Shorter than this is a greeting or a yes.
MIN_USER_CHARS = 40

#: One reflection per agent per this many seconds, and this many in flight
#: per process. Free models are free of money, not of quota: 1,000 requests
#: a day on this key, shared with everything else on the platform.
REFLECT_MIN_INTERVAL_SECONDS = 90
REFLECT_MAX_IN_FLIGHT = 2

#: The service's own sentences that must never be reflected on as if the
#: agent had said them. Kept as prefixes because two of them carry a name.
_NOT_AN_ANSWER_PREFIXES = (
    "PASS",
    "This agent is set to a model that cannot run an agent.",
    "The free models are all busy right now",
    "There was nothing to answer.",
    "Stopped after",
)

_KEY_STRIP_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def memory_key(text: str) -> str:
    """The note as a dedup key: lower case, letters digits and spaces only,
    single spaces, 120 characters."""
    out = _KEY_STRIP_RE.sub(" ", (text or "").lower())
    return _WS_RE.sub(" ", out).strip()[:120]


def _fit(items: list[str], budget: int) -> list[str]:
    """The leading items that fit the budget, whole items only."""
    out: list[str] = []
    spent = 0
    for item in items:
        line = "- " + item + "\n"
        if spent + len(line) > budget:
            break
        out.append(item)
        spent += len(line)
    return out


def render_recall(notes: list[str], facts: list[str]) -> str:
    """Both stores as one block, or "" when both are empty.

    Caller passes newest first; the budget keeps the front of each list.
    Rendered as plain lines under two headings, in the second person,
    because it sits inside the identity line that already speaks that way.
    """
    parts = []
    kept_notes = _fit([n for n in notes if n], NOTES_BUDGET_CHARS)
    kept_facts = _fit([f for f in facts if f], FACTS_BUDGET_CHARS)
    if kept_notes:
        parts.append("Your notes from earlier conversations with this person, "
                     "newest first. Use them; do not repeat them back unless "
                     "asked:\n" + "\n".join("- " + n for n in kept_notes))
    if kept_facts:
        parts.append("Known about this person:\n"
                     + "\n".join("- " + f for f in kept_facts))
    return "\n\n".join(parts)[:RECALL_BUDGET_CHARS]


def _clean_items(raw) -> list[str]:
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, str):
            continue
        item = _WS_RE.sub(" ", item).strip()[:MAX_ITEM_CHARS]
        if len(item) < MIN_ITEM_CHARS:
            continue
        if item.endswith("?") or item.upper() == "PASS":
            continue
        out.append(item)
        if len(out) >= MAX_ITEMS_PER_KIND:
            break
    return out


def parse_reflection(text: str) -> tuple[list[str], list[str]]:
    """(notes, facts) from whatever the model wrote. Lenient on purpose:
    the JSON is found between the first "{" and the last "}", so prose and
    code fences around it do not matter. Anything that is not the shape
    asked for parses to nothing rather than raising."""
    text = text or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return [], []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return [], []
    if not isinstance(data, dict):
        return [], []
    return _clean_items(data.get("notes")), _clean_items(data.get("facts"))


def should_reflect(user_text: str, answer: str) -> bool:
    """Whether this turn is worth one free completion."""
    if len((user_text or "").strip()) < MIN_USER_CHARS:
        return False
    answer = (answer or "").strip()
    if not answer:
        return False
    return not any(answer.startswith(p) for p in _NOT_AN_ANSWER_PREFIXES)


def reflection_prompt(agent_name: str, notes: list[str], facts: list[str],
                      user_text: str, answer: str) -> str:
    known = ("Notes it already has:\n" + "\n".join("- " + n for n in notes)
             if notes else "Notes it already has: none.")
    facts_block = ("Facts already known about the person:\n"
                   + "\n".join("- " + f for f in facts)
                   if facts else "Facts already known about the person: none.")
    return (
        "You are the memory of an assistant called %s. Below is what it "
        "already remembers, then one exchange it just had with the person "
        "it works for. Write down only what is worth keeping for a month: "
        "decisions, preferences, names, numbers, commitments, open items.\n\n"
        "%s\n\n%s\n\n"
        "The person said:\n%s\n\nThe assistant answered:\n%s\n\n"
        "Return JSON only, of the shape {\"notes\": [], \"facts\": []}. "
        "notes: things about this assistant's own work with the person, "
        "what it did, what is open, how they want its output. "
        "facts: lasting things about the person that any assistant should "
        "know, preferences, people, places, names. Up to 3 of each, one "
        "sentence each, under 200 characters, in the third person, with no "
        "reference to this conversation, and nothing that is already in the "
        "lists above. Never store a guess, a question, a greeting or a "
        "thank you. If nothing is worth keeping, return exactly "
        "{\"notes\": [], \"facts\": []}."
        % (agent_name or "this assistant", known, facts_block,
           (user_text or "")[:2000], (answer or "")[:2000]))
