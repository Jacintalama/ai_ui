"""Answering "can you do X" from what is true, not from the model's idea
of itself (2026-11-12).

Found live 2026-11-11, minutes after Airtable one-click went in. Ralph
asked the main chat "can you access airtable?" and was told "I don't have
Airtable access in this chat, so I can't read from or write to your
Airtable bases directly right now." Every word of that was false: the
credential was stored, a real call returned his account and his base, and
his exact words ranked `my-airtable_list_tables` top of everything he can
reach.

Nothing was broken. Jev picks tools for a TASK and picks none for a
CAPABILITY QUESTION, which is right on its own terms, there being nothing
to fetch in order to answer "can you". But with no tool picked the free
model answers alone, and its idea of itself is a general model that has
never heard of this platform.

So the facts go in front of it. Which apps this person has connected is a
row in a table and what IO can do with each is already written down, tool
by tool, in `app_triage.APPS`, which is checked against the real tool
catalogue by its own tests. The model only does the wording.

NARROW ON PURPOSE. "An ordinary question goes straight to the free model"
(CLAUDE.md) is worth keeping, because the assistant turn is the slow path:
"check my inbox" took 9.5 seconds on the live box. So this fires only for
a question about ability that NAMES an app this platform knows, or for
"what can you do" itself. "Can you explain how DNS works" is not that
question and is left exactly as it was.

Pure: no network, no database, no model, so every rule here is tested on
its own.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import app_triage

#: Said before the connections are read, because the read takes a moment
#: and a silent chat looks like a broken one.
CHECKING_LINE = "Checking what you have connected..."

#: Ways of asking whether IO is ABLE to do something, rather than asking
#: it to do the thing. "could you" is here with the rest: it is the same
#: question in English, and a polite request that names an app is better
#: answered knowing what IO can do with it than guessing.
_ASKS = (
    "can you", "can u", "could you", "could u", "can i", "could i",
    "are you able", "is it possible for you", "do you have access",
    "do you have", "are you connected", "have you got", "able to access",
)

#: The general form, where nothing is named and the answer is everything
#: this person has.
_GENERAL = (
    re.compile(r"\bwhat\s+(?:else\s+)?(?:can|could)\s+(?:you|u)\s+do\b"),
    re.compile(r"\bwhat\s+are\s+(?:you|u)\s+able\s+to\s+do\b"),
    re.compile(r"\bwhat\s+(?:apps|integrations|tools)\s+"
               r"(?:can|do)\s+(?:you|u)\b"),
)


def _words_for(app) -> tuple:
    """Every word that means this app: its id, its label, and the
    catalogue's own list of other words an answer uses for it, so there is
    not a second list here to keep in step with that one."""
    return (app.id.lower(), app.label.lower()) + tuple(
        str(w).lower() for w in (app.says or ()))


def apps_named(text: str) -> List[str]:
    """The apps this text names, in the order they were said.

    Whole words only. "driven development" is not Google Drive, and that
    is the kind of match that turns a careful answer into a strange one.
    """
    low = str(text or "").lower()
    found: Dict[str, int] = {}
    for app in app_triage.APPS.values():
        for word in _words_for(app):
            hit = re.search(r"\b" + re.escape(word) + r"\b", low)
            if hit and (app.id not in found or hit.start() < found[app.id]):
                found[app.id] = hit.start()
    return [i for i, _at in sorted(found.items(), key=lambda p: p[1])]


def question(text: str) -> Optional[List[str]]:
    """The apps a question about IO's abilities is about.

    `None` when this is not that question, which is nearly every message.
    `[]` for the general "what can you do". A list of app ids otherwise.
    """
    low = " ".join(str(text or "").lower().split())
    if not low:
        return None
    if any(p.search(low) for p in _GENERAL):
        return []
    if not any(a in low for a in _ASKS):
        return None
    named = apps_named(low)
    return named or None


def plan(ids, connected, rejected=()) -> dict:
    """What to tell the model, as `app_triage.with_buttons` also reads it.

    With apps named, those apps. With none named, the general question:
    everything this person has connected, plus the rest of the catalogue
    as what they could connect, because "what can you do" asked by
    somebody with nothing connected is not answered by "nothing".

    `rejected` is the providers whose credential was refused the last
    time it was used (`connection_health.rejected`). Connected is not the
    same as usable: measured live 2026-11-12, "what can you do" listed
    GitHub among the answers while that credential had been answering 401
    since the morning and the Connections card already said so.
    """
    have = set(connected or ())
    bad = set(rejected or ())
    general = not ids
    if general:
        chosen = [a for a in app_triage.APPS.values() if a.id in have]
    else:
        chosen = [app_triage.APPS[i] for i in ids or []
                  if i in app_triage.APPS]
    return {
        "apps": [{"id": a.id, "label": a.label, "connected": a.id in have,
                  "rejected": a.id in bad, "can": a.can, "cannot": a.cannot}
                 for a in chosen],
        "general": general,
        "rest": [a.label for a in app_triage.APPS.values()
                 if a.id not in have] if general else [],
    }


def brief(p) -> str:
    """The block put in front of the assistant. Empty when there is
    nothing true to say, so an empty instruction is never sent."""
    apps = (p or {}).get("apps") or []
    rest = (p or {}).get("rest") or []
    if not apps and not rest:
        return ""
    lines = ["What IO can do for this person, read from their own "
             "connections just now rather than remembered. This is the "
             "truth about this platform, so say nothing about IO's "
             "abilities that contradicts it:"]
    for a in apps:
        state = "connected" if a["connected"] else "not connected"
        if a.get("rejected"):
            # A credential that answers 401 is a connection in the table
            # and nothing in practice, and the Connections card already
            # says so. Saying "connected" alone here is how the chat came
            # to offer GitHub while GitHub was refusing every call.
            state = ("connected, but the credential was rejected the last "
                     "time it was used, so it has to be reconnected from "
                     "Connections before IO can use it")
        line = "- %s (%s). IO can %s." % (a["label"], state, a["can"])
        if a["cannot"]:
            line += " IO cannot %s yet." % a["cannot"]
        lines.append(line)
    if rest:
        lines.append("Not connected yet, each one a button away under "
                     "Connections: " + ", ".join(rest) + ".")
    lines.append(
        "Answer what they asked from this list and nothing else. Never say "
        "IO cannot do something this list says it can, and never offer "
        "something it says IO cannot. For an app that is not connected, say "
        "it has to be connected first: a Connect button is added under your "
        "answer, so do not write a link yourself. This list is the whole "
        "answer, so do not say you are about to go and check, and do not "
        "promise to look in a moment: say what IO can do and stop.")
    return "\n".join(lines)
