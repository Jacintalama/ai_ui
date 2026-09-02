"""Which of a person's agents they are speaking to.

Ported from the channel gateway's agent_router, which has matched names in
Discord and Telegram for weeks. The rule is a whole-word, case-insensitive
match on the agent's name anywhere in the sentence, because people write
"hi mia, are you there" rather than an @mention. That is also why an agent's
name has to be one word: a name with a space in it is not something anybody
says mid sentence and cannot be found in free text reliably.

The failure that matters is the false positive. Waking an agent nobody asked
for hijacks the conversation and costs a model call, and it happens silently.
Missing a wake just means the person says the name again.

A collective word ("team", "everyone", "all of you", "guys") is the same
idea aimed at every agent at once, and it uses the same hand-rolled word
boundary for the same reason: "team" must not fire inside "teamwork" or
"steam", and "guys" must not fire inside "guyshire".
"""
import re

#: Said to address every agent at once rather than one by name. Matched with
#: the same hand-rolled word boundary as an agent's name, so "team" inside
#: "teamwork" or "steam" is not a match, same failure mode as a name.
COLLECTIVE_WORDS = frozenset({"team", "everyone", "all of you", "guys"})

#: Said to send the current agent back to sleep. Matched against the WHOLE
#: message, lower-cased and stripped, never as a substring: somebody who
#: writes "stop the server from crashing" is not dismissing their agent.
RELEASE_PHRASES = frozenset({
    "stop", "stop it", "stop using that", "stop using it",
    "never mind", "nevermind", "back to normal", "go back to normal",
    "no agent", "plain chat", "release", "dismiss",
})


def wants_release(text: str) -> bool:
    """True when the whole message is a request to release the agent."""
    return (text or "").strip().lower().rstrip(".!") in RELEASE_PHRASES


def _whole_word_hit(hay: str, word: str) -> bool:
    """True when `word` appears in `hay` on a hand-rolled word boundary.

    The one boundary rule this whole module leans on: not \\b, so that a
    match cannot land in the middle of a longer word. Shared by name
    matching and collective-word matching so both get the same guarantee.
    """
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])",
                     hay, re.IGNORECASE) is not None


def _is_collective(hay: str) -> bool:
    """True when the text addresses every agent at once rather than one."""
    return any(_whole_word_hit(hay, word) for word in COLLECTIVE_WORDS)


def match_agents(text: str, agents) -> list[dict]:
    """Every agent the message addresses, in the order that makes sense.

    A name is matched in spoken order: word boundaries are hand rolled
    rather than \\b so that an agent called "Ada" is not summoned by "adapt"
    and one called "Mia" is not summoned by "Miami". Each agent appears at
    most once, at the position of its first mention, even if its name is
    said more than once.

    A collective word ("hi team", "everyone", "all of you", "guys") means
    every agent at once, so it returns all of them in the order they were
    given rather than spoken order, since there is no single position for
    "everyone". A collective word combined with a name still returns every
    agent exactly once; the collective wins rather than being unioned with
    the name match, which is what keeps the result free of duplicates.

    Never raises. The agent list arrives from a model listing over HTTP, so a
    wrong shape is expected rather than exceptional, and an exception here
    would take down every message in the chat.
    """
    hay = text if isinstance(text, str) else ""
    if not isinstance(agents, (list, tuple)):
        return []

    valid = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            continue
        valid.append(a)

    if _is_collective(hay):
        return list(valid)

    found = []
    for a in valid:
        name = a["name"].strip()
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])",
                      hay, re.IGNORECASE)
        if m:
            found.append((m.start(), a))
    found.sort(key=lambda pair: pair[0])
    return [a for _, a in found]


def match_agent(text: str, agents) -> dict | None:
    """The FIRST agent whose name is spoken, or None.

    Thin wrapper over match_agents, kept for callers that only ever act on
    one agent at a time.
    """
    matches = match_agents(text, agents)
    return matches[0] if matches else None


def last_user_text(messages) -> str:
    """The most recent thing the person actually typed.

    Reads backwards rather than taking messages[-1], because a tool result or
    an assistant turn can be last.
    """
    if not isinstance(messages, (list, tuple)):
        return ""
    for m in reversed(messages):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
    return ""
