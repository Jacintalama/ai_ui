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


def addresses_everyone(text) -> bool:
    """True when a collective word put this to the room rather than to one.

    Public because the caller needs to tell the two kinds of match apart and
    match_agents cannot say: it returns every agent for "hey everyone" and for
    "Ada and Mia" alike. The difference matters because naming somebody is a
    question put to them, and addressing a room is not.
    """
    return _is_collective(text if isinstance(text, str) else "")


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


def _label_line_re(names):
    """A line that is exactly one of these names, nothing else.

    Two shapes are matched. The rendered reply used to put "Ada:" on its own
    line and now puts "**Ada**", so a live conversation can hold both: the
    turns from before the format changed sit above the turns from after, and
    an agent must see neither.

    Only KNOWN agent names, so a reply genuinely opening with "Note:" or
    "Warning:" on its own line is left alone.
    """
    cleaned = sorted({str(n).strip() for n in names if str(n).strip()},
                     key=len, reverse=True)
    if not cleaned:
        return None
    alts = "|".join(re.escape(n) for n in cleaned)
    return re.compile(
        r"^[ \t]*(?:(?:%s)[ \t]*:|\*\*(?:%s)\*\*)[ \t]*$" % (alts, alts),
        re.IGNORECASE | re.MULTILINE)


def strip_label_lines(text, names) -> str:
    """Remove every line that is just an agent's name and a colon.

    Rendered replies carry those lines so a person can see who spoke. Fed
    back to an agent as history, the same lines teach it a format, and it
    starts prefixing its own answers with a name, or worse, writing whole
    fake exchanges between the agents. Seen live 2026-09-04: one agent's
    answer contained a made up reply from the other. So history is cleaned
    of the labels before an agent sees it, keeping every word that was
    actually said.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    pattern = _label_line_re(names)
    if pattern is None:
        return text
    out = pattern.sub("", text)
    # Collapse the blank runs the removed lines leave behind, so the
    # agent does not see a wall of empty lines where labels were.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def strip_leading_labels(text, names) -> str:
    """Remove label lines from the START of an answer only.

    The defensive half of the same fix: even with clean history a model can
    echo a name it saw elsewhere, and the renderer is about to add the real
    label in front of this text. Two labels stacked is exactly what the
    person saw. Only leading lines go; a name mentioned inside the answer
    is the agent's own words and stays.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    pattern = _label_line_re(names)
    if pattern is None:
        return text
    lines = text.split("\n")
    i = 0
    while i < len(lines) and (not lines[i].strip() or pattern.match(lines[i])):
        i += 1
    return "\n".join(lines[i:]).strip()


#: What an agent says when it has nothing to add.
PASS_TOKEN = "PASS"

#: The line a routing pipe appends to whatever the model it picked said:
#: "*Auto (Smart): routed to the {tier} {category} model `{model}`.*"
#: (open-webui-functions/auto_smart_pipe.py _footer) and "*Auto-routed to the
#: free {category} model `{model}`.*" (auto_router_pipe.py _footer). Only
#: ever the last line, and only on its own line. An agent cannot run on
#: Auto (Free) today (it is a callback model, see AGENT_ON_CALLBACK_MODEL),
#: so that shape is here because it is the same footer and costs nothing,
#: not because it has been seen in the room.
ROUTE_FOOTER = re.compile(
    r"\n[ \t]*\*(?:Auto \(Smart\): routed|Auto-routed) to the [^*\n]+ "
    r"model `[^`\n]*`\.\*\s*\Z")

#: A line that is only a speaker label: an optional **, one name, an
#: optional ** and an optional colon. Any one word name rather than a known
#: one (a name is one word, see the module docstring), because the paid move
#: in agent_runner reads a PASS too and does not know the room's names.
_ANY_LABEL_LINE = re.compile(
    r"^[ \t]*(?:\*\*)?[ \t]*[^\W_][\w.'-]*[ \t]*(?:\*\*)?[ \t]*:?[ \t]*"
    r"(?:\*\*)?[ \t]*$")


def is_pass(answer: object) -> bool:
    """An agent declining to speak. The one definition the room and the paid
    move both use: when they disagreed, an unnamed agent whose free answer
    was "Ada:" over PASS was re-asked on the paid model, and at the day's cap
    the cap sentence was added to a PASS and drawn (review, 2026-09-18).

    Generous about the shape because models are: a bare PASS, a PASS with a
    full stop, a PASS in quotes. Anything longer is an answer that happens to
    contain the word.

    Two additions that are not the word itself. Label lines in front of it,
    "Ada:" or "**Ada**" on their own line, which a model echoes from the
    rendered history. And a routing pipe's footer after it: an agent on Auto
    (Smart) that passes comes back as PASS plus "*Auto (Smart): routed to
    the paid general model `gpt-5.5`.*", stored exactly like that on
    production, and read as an answer it was drawn as a bubble saying PASS
    and stopped the everybody-passed fallback from running. Nothing else is
    taken off: Kai's stored "PASS" followed by a paragraph about the files it
    read is still an answer, because it says something.
    """
    if not isinstance(answer, str):
        return False
    body = ROUTE_FOOTER.sub("", "\n" + answer)
    lines = [line for line in body.splitlines() if line.strip()]
    while len(lines) > 1 and _ANY_LABEL_LINE.match(lines[0]):
        del lines[0]
    return (len(lines) == 1
            and lines[0].strip().strip('."\'').upper() == PASS_TOKEN)


def clean_history_for_agent(messages, names) -> list:
    """The conversation as one agent should see it: every assistant turn
    with the speaker labels removed. User turns are untouched, since a
    person typing "Mia:" meant to."""
    cleaned = []
    if not isinstance(messages, list):
        return cleaned
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant" and isinstance(m.get("content"), str):
            m = dict(m)
            m["content"] = strip_label_lines(m["content"], names)
        cleaned.append(m)
    return cleaned


#: The owner has a standing rule against these, and the shared brief says so,
#: and gpt-5-mini used one in 25 of 36 replies measured on 2026-09-14 while
#: that rule was live. Asking did not work, so every answer is cleaned on the
#: way out instead. Order matters: bullets first, then number ranges, then
#: everything else, then the punctuation the replacement leaves doubled.
_DASH_BULLET = re.compile("^[ \t]*[\u2013\u2014][ \t]+", re.M)
_EN_DASH_RANGE = re.compile("(\\d)[ \t]*\u2013[ \t]*(\\d)")
_EM_DASH_RANGE = re.compile("(\\d)[ \t]*\u2014[ \t]*(\\d)")
_ANY_LONG_DASH = re.compile("[ \t]*[\u2013\u2014][ \t]*")
_COMMA_BEFORE_PUNCT = re.compile(",[ \t]*([,.;:!?)])")
_COMMA_AT_LINE_END = re.compile(",[ \t]*$", re.M)
#: A fenced block, closed or running to the end, or an inline code span. Code
#: is what someone pastes into a file, so it comes back exactly as written;
#: the first live run turned "<title>Shoe Product \u2014 Landing" into a comma.
_CODE = re.compile("```.*?(?:```|\\Z)|`[^`\n]*`", re.S)


def scrub_long_dashes(text):
    """The same text with every em-dash and en-dash replaced, outside code.

    A dash used as a bullet becomes a hyphen bullet, an en-dash between two
    numbers becomes a hyphen ("7-11"), an em-dash between two numbers becomes
    "to" (a date range), and any other becomes a comma. Code blocks and inline
    code are left exactly as written. Text with no long dash comes back
    unchanged, and anything that is not text comes back as it was.
    """
    if not isinstance(text, str):
        return text
    if "\u2014" not in text and "\u2013" not in text:
        return text
    # Code is swapped for placeholders rather than cut out, so the text around
    # it keeps its real line starts: after a code span is not a new line, and
    # a dash there is not a bullet.
    code = []

    def _hold(m):
        code.append(m.group(0))
        return "\ue000%d\ue001" % (len(code) - 1)

    out = _scrub_prose(_CODE.sub(_hold, text))
    return re.sub("\ue000(\\d+)\ue001", lambda m: code[int(m.group(1))], out)


def _scrub_prose(text: str) -> str:
    if "\u2014" not in text and "\u2013" not in text:
        return text
    out = _DASH_BULLET.sub("- ", text)
    out = _EN_DASH_RANGE.sub(r"\1-\2", out)
    out = _EM_DASH_RANGE.sub(r"\1 to \2", out)
    out = _ANY_LONG_DASH.sub(", ", out)
    out = _COMMA_BEFORE_PUNCT.sub(r"\1", out)
    out = _COMMA_AT_LINE_END.sub("", out)
    return out
