"""A short name for a schedule, made from what it is asked to do.

Why (2026-11-24, the Cron Jobs page): schedules made from Discord and Slack
were named "every day at 7:00 PM: give me the best quote for this day and
send give me news up", which is the time and the prompt pasted together.
The card already shows the time on its own line, and Cron Outputs lists
runs by name, so the name was the one place nothing new was said.

Deterministic on purpose: it runs on every create, it must never fail or
wait on a model, and a test can say exactly what it does.
"""
from __future__ import annotations

import re

#: The longest name made here, in characters and in words.
MAX_CHARS = 40
MAX_WORDS = 6

FALLBACK = "Scheduled task"

#: Said before the request, never part of what it is.
_POLITE = re.compile(
    r"^(please|pls|kindly|hey|hi|ok(ay)?|so|can you|could you|would you|"
    r"will you|i want you to|i need you to|i would like you to|"
    r"i'd like you to)\b[\s,:]*", re.I)

#: When it runs. The card says that on its own line.
_TIMING = re.compile(
    r"^(every|each)\s+(day|morning|evening|night|weekday|weekend|week|month|"
    r"hour|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d+\s+(minutes?|hours?|days?))s?\b[^,:]*?(\bat\s+[\d:]+\s*(am|pm)?)?"
    r"[\s,:]*|"
    r"^(daily|weekly|monthly|hourly|tonight|today|tomorrow|"
    r"in the (morning|evening))\b[\s,:]*|"
    r"^(at|by)\s+[\d:]+\s*(am|pm)?\b[\s,:]*|"
    r"^on\s+(mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|"
    r"sundays?|weekdays|weekends)\b[\s,:]*", re.I)

#: "give me", "send me" and friends: the name is what is given.
_ASKING = re.compile(
    r"^(give|send|tell|show|get|find|bring|fetch|email|text|message)\s+"
    r"(me|us|the user|the team)\b\s*", re.I)

#: An article or possessive at the front of what is left says nothing.
_LEAD = re.compile(r"^(the|a|an|some|our)\s+", re.I)

#: The first clause is the request; what follows "and" is usually a second
#: one, and a name is for the first.
_CLAUSE = re.compile(r"\s+(and|then|also|plus)\s+|[,;.!?\n(]")

#: A name does not end on a word that needs another after it.
_DANGLING = {"the", "a", "an", "of", "for", "to", "and", "with", "in", "on",
             "at", "my", "your", "our", "from", "by", "or", "that", "this",
             "about", "into", "is", "are"}


def short_name(prompt: str) -> str:
    """A name of a few words for what `prompt` asks for."""
    text = " ".join(str(prompt or "").split())
    for _ in range(4):
        before = text
        text = _POLITE.sub("", text)
        text = _TIMING.sub("", text)
        if text == before:
            break
    text = _ASKING.sub("", text)
    text = _LEAD.sub("", text)
    text = _CLAUSE.split(text, maxsplit=1)[0].strip(" :-")
    words = text.split()[:MAX_WORDS]
    while words and len(" ".join(words)) > MAX_CHARS:
        words.pop()
    while words and words[-1].lower().strip(".,:;") in _DANGLING:
        words.pop()
    if not words:
        return FALLBACK
    name = " ".join(words)
    return name[0].upper() + name[1:]


def _plain(text: str) -> str:
    return " ".join(str(text or "").lower().split()).rstrip(".")


def is_made_from_prompt(name: str, prompt: str) -> bool:
    """Whether `name` is only the prompt again, maybe after a time and a
    colon: the shape the Discord and Slack bots give a schedule. A name
    somebody chose is never one of these, so it is never replaced."""
    n, p = _plain(name), _plain(prompt)
    if not n:
        return True
    if not p:
        return False
    if p.startswith(n.rstrip(". ")) and len(n) >= 12:
        return True
    head, sep, rest = n.partition(": ")
    rest = rest.rstrip(". ")
    return bool(sep) and len(rest) >= 8 and p.startswith(rest) \
        and len(head) <= 60


def name_for(name: str, prompt: str) -> str:
    """The name to store: the one given, unless it is only the prompt."""
    if is_made_from_prompt(name, prompt):
        return short_name(prompt)
    return str(name).strip()
