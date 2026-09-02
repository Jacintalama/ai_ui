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
"""
import re

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


def match_agents(text: str, agents) -> list[dict]:
    """Every agent whose name is spoken, in the order they were said.

    Word boundaries are hand rolled rather than \\b so that an agent called
    "Ada" is not summoned by "adapt" and one called "Mia" is not summoned by
    "Miami". Each agent appears at most once, at the position of its first
    mention, even if its name is said more than once.

    Never raises. The agent list arrives from a model listing over HTTP, so a
    wrong shape is expected rather than exceptional, and an exception here
    would take down every message in the chat.
    """
    hay = text if isinstance(text, str) else ""
    if not isinstance(agents, (list, tuple)):
        return []
    found = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            continue
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
