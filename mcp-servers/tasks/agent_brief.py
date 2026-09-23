"""Who an agent is and how it is told to work, as one system line.

Extracted from routes_agent_turn 2026-09-23, unchanged, because it was
reachable from exactly one of the four ways an agent runs. brief_for was
called at a single site inside the chat path, so an agent answering on
Discord or waking on a schedule got its stored memory and nothing else: no
skills, no account context, no roster, not even its own role. An agent whose
whole point was meta.skillIds ran its weekly cron without the skill.

It lives in its own module rather than in the turn router because
routes_agent_turn imports agent_runner, so the schedule path could only
reach back into it with a deferred import. One more module breaks the cycle
instead of adding another loop through it.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import agent_skills

logger = logging.getLogger(__name__)

#: An agent whose owner picked its tools by hand reaches only those. Read the
#: same way in tools_for_agent, so the brief and the tools actually attached
#: can never describe different agents.
TOOL_SCOPE_PICKED = "picked"

#: A role is typed by the owner into a form whose input caps at 32. This cap
#: is the brief's own defence, not the form's: meta comes off a database row
#: that Open WebUI's model API writes, so nothing here can assume the form was
#: the last thing to touch it.
ROLE_MAX_CHARS = 40


def _role_of(agent: dict) -> str:
    """The agent's job, ready to drop into the middle of a sentence.

    Empty when there is none, which is the ordinary case: every agent that
    existed before the field did has no role, and the field is optional.

    Typed into a form a role arrives capitalised, and "You are Ada, this
    person's Project manager" reads as a proper noun. So the first letter is
    lowered, EXCEPT when the first word is an initialism, because "qa lead"
    and "hr assistant" are worse than the capital they fix.
    """
    meta = agent.get("meta")
    role = meta.get("role") if isinstance(meta, dict) else None
    if not isinstance(role, str):
        return ""
    role = " ".join(role.split())[:ROLE_MAX_CHARS].strip()
    if not role:
        return ""
    first = role.split(" ", 1)[0]
    if len(first) > 1 and first.isupper():
        return role
    return role[0].lower() + role[1:]


#: What each tool reaches, in the words the owner would use. Kept here rather
#: than imported from routes_agents, which imports this module.
_TOOL_WORDS = {
    "gmail": "email",
    "calendar": "the calendar",
    "gdrive": "Drive",
    "code": "the apps they build",
    "schedules": "their schedules",
    "remember": "saved notes",
    "documents": "making documents",
    "excel_creator": "making spreadsheets",
    "executive_dashboard": "making dashboards",
    "account": "their account and connections",
    "server:mcp-proxy": "their connected apps and the web",
    "agents": "the other assistants",
}


def _own_tools(agent: dict):
    """This agent's own tools when it is narrowed, or None when it reaches
    everything. The same rule tools_for_agent applies, so the brief and the
    tools actually attached can never describe different agents."""
    meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
    own = [t for t in (meta.get("toolIds") or []) if isinstance(t, str)]
    if meta.get("toolScope") == TOOL_SCOPE_PICKED and own:
        return own
    return None


def _reaches(agent: dict, tool_id: str) -> bool:
    own = _own_tools(agent)
    return own is None or tool_id in own


def _join_words(words: list) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _tools_sentence(agent: dict) -> str:
    """What this agent can reach, and what to do about the rest.

    It used to say the same thing to every agent: that it had tools for
    mail, files, apps, connections, schedules and saved notes. True of an
    agent with everything, false of every narrowed one, so Mia, Nora and Iris
    each offered to bug-hunt an app none of them can open.
    """
    base = ("When they ask about their own things, use a tool and answer "
            "from what it returns. Never state a number or a name you have "
            "not looked up. Never describe what you could do instead of "
            "doing it: if you can check, check, then say what you found.")
    own = _own_tools(agent)
    if own is None:
        return "You have tools that read this person's real account. " + base
    reach = [_TOOL_WORDS.get(t, t) for t in own if t != "skills"]
    if not reach:
        return base
    return ("Your tools reach %s, and nothing else. %s Anything that needs "
            "another tool is not yours to do: say so or pass, and never "
            "offer to do it." % (_join_words(reach), base))


def _others_with_roles(roster, me: str) -> list[str]:
    """The other assistants, each with its job, as "Mia (receptionist)".

    Asked "who handles coding?", Kai said he did, Ada said Kai was the lead
    and Rex also worked on it, and Rex said he did (Ralph's screenshot,
    2026-09-18). All three were guessing: the brief listed the other agents
    by name and never said what any of them was for, so each one filled the
    gap from its own instructions.

    Accepts plain names as well as agent rows, because `names` is a list of
    strings on every surface that also feeds it to clean_history_for_agent.
    A name with no role reads as a bare name, exactly as before.
    """
    out: list[str] = []
    for entry in roster or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            role = _role_of(entry)
        else:
            name = str(entry or "").strip()
            role = ""
        if not name or name == me:
            continue
        out.append("%s (%s)" % (name, role) if role else name)
    return out


def now_in(tz_name: str) -> datetime:
    """The current time on somebody's own clock, or UTC.

    The name is whatever the browser last reported into tasks.user_prefs, or
    whatever is stored on a schedule, so it is not this code's to trust: an
    unknown zone must cost the sentence its accuracy, never the turn.
    """
    if not tz_name:
        return datetime.now(timezone.utc)
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:                                       # noqa: BLE001
        logger.warning("unknown timezone %r, using UTC", tz_name)
        return datetime.now(timezone.utc)


def _clock_sentence(now: datetime) -> str:
    """What day and time it is, written the way a person writes it.

    strftime pads the day and the hour, and "Friday 03 September, 08:05am"
    is not how anybody writes a date to somebody else.

    The zone is named because an agent runs on somebody else's clock. A
    schedule fires on the zone stored against it, and "8:14pm" with nothing
    after it invites an agent in Manila to report a London morning.
    """
    day = "%s %d %s %d" % (now.strftime("%A"), now.day,
                           now.strftime("%B"), now.year)
    clock = "%d:%02d%s" % (now.hour % 12 or 12, now.minute,
                           now.strftime("%p").lower())
    # The zone's own key, not %Z. strftime renders Asia/Manila as "PST",
    # which is also how it renders Pacific Standard Time, sixteen hours away.
    # An abbreviation that means two places is worse than no abbreviation.
    zone = getattr(now.tzinfo, "key", None) or now.strftime("%Z") or "UTC"
    return "Today is %s, and the time is %s in %s." % (day, clock, zone)


def build(agent: dict, names, memory: str = "", roster=(),
          graph: str = "", now: datetime | None = None) -> dict:
    """Who the agent is and how it is expected to work, as one system line.

    Two faults, both seen live, both fixed here rather than on any one card.

    It did not know its own name. The transcript it reads has every speaker
    label stripped, because those lines taught it to invent exchanges between
    agents, and that fix left it with nothing to go on: asked "where is Ada",
    Ada answered that Ada was somebody else.

    And it would not use what it had. Asked "who has all my app connections"
    it guessed at a number; asked "do you have any work today" it offered to
    help rather than looking. It now holds tools that read the person's real
    account, so the brief says to use them and says that guessing is worse
    than saying it could not check.

    A system line is not the hazard a labelled transcript is: it states an
    identity rather than demonstrating a format, and it says in as many words
    not to write the name into the answer, which the renderer adds.
    """
    me = str(agent.get("name") or agent.get("id") or "this assistant")
    # The roster carries each agent's job; `names` is the same list with only
    # the names, which is what the history cleaners take. Either works here.
    others = _others_with_roles(roster or names, me)

    role = _role_of(agent)
    said = ["You are %s, this person's %s." % (me, role) if role
            else "You are %s, one of this person's own assistants." % me]
    # Second, before anything it is asked to do. Nothing else in a turn says
    # what day it is: the per-user clock is an Open WebUI inlet filter and an
    # agent turn does not pass through filters, so a daily briefing had no
    # way to tell today from the day it was written.
    said.append(_clock_sentence(now or datetime.now(timezone.utc)))
    if others:
        said.append(
            "The other assistants here are %s. They are software, like you, "
            "not this person's colleagues: when they say team or everyone "
            "they mean you and the other assistants, so answer for yourself "
            "rather than suggesting they go and ask somebody. Never answer "
            "for them or invent what they said. Earlier replies here came "
            "from several of you, so never say you changed or checked "
            "something unless you did it in this reply." % ", ".join(others))

    said.append(_tools_sentence(agent))

    said.append(
        "Asked what you do or what you are working on, answer from your own "
        "instructions in terms of this person's actual work, in a sentence or "
        "two. Do not describe yourself as an assistant who can help with a "
        "variety of tasks; they know that already and it tells them nothing.")

    # The owner reads every one of these and asked for it directly. The dash
    # is also how a whole room of agents ends up sounding identical: they all
    # reach for the same punctuation, so seven replies look like one voice
    # repeated. Spelled out with the characters named, because "avoid
    # em-dashes" does not survive a model that does not know which key that is.
    said.append(
        "Never use the long dashes — or –. Use a comma, a full stop "
        "or the word and. This person will notice.")

    said.append(
        "You can see this whole conversation. Do not say again what you have "
        "already said in it: if they have seen a list, do not print it a "
        "second time, refer to it. When they tell you something is handled, "
        "not needed, or already dealt with, that settles it, and raising it "
        "again is the same as not listening.")

    said.append(
        "Answer the question they actually asked. Running your usual job and "
        "reporting the result is not an answer to a different question.")

    if _reaches(agent, "remember"):
        said.append(
            "You have a tool for remembering things. When they tell you "
            "something worth keeping, a preference, a decision, a name, save "
            "it, so the next conversation starts where this one ended.")

    # A narrowed agent without the skills tool still gets its assigned skills
    # through brief_for below; telling it to call find_skills only spends a
    # round on "not available".
    if _reaches(agent, "skills"):
        said.append(
            "Before doing a job you have no instructions for, call find_skills "
            "with what they asked in their own words. If one fits, use_skill "
            "and follow it. If none does, do the job and say so.")

    said.append(
        "Answer, then stop. Do not close with an offer of further help or an "
        "invitation to let you know. If something is genuinely out of reach, "
        "say what is missing and what would fix it, rather than apologising.")

    said.append(
        "Answer as yourself. Do not put your own name at the start of your "
        "answer; it is added for you.")

    content = " ".join(said)
    # Appended, never in place of the above. The brief exists because an agent
    # did not know its own name; a skill adds a job to that, it does not
    # replace who is doing it. Joined with a blank line rather than a space
    # because a skill is a markdown document, not another sentence.
    chosen = agent_skills.brief_for(agent.get("meta"))
    if chosen:
        content += "\n\n" + chosen
    # Last, after the skills. What the agent remembers is the most specific
    # thing in the line and the thing most likely to answer the question
    # being asked, so it sits nearest the conversation. Empty for an agent
    # with nothing stored, which keeps every existing turn byte identical.
    # The person's own account, from the Brain. Before the memory block and
    # after the skills, because it is context rather than instruction: it says
    # what exists, where a skill says what to do and memory says what this
    # agent was told. Empty for anybody whose graph has nothing in it, and
    # empty whenever the read failed, which costs the turn nothing.
    if graph:
        content += "\n\n" + graph
    if memory:
        content += "\n\n" + memory
    return {"role": "system", "content": content}
