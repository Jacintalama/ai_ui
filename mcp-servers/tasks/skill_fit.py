"""Which apps a skill needs, and which of those a person has not connected.

Lukas, 2026-11-03: "I would want the AI to kind of suggest skills based on
the things that the user has connected." Pure, so every rule is tested with
no database and no model. Callers bring the person's connections
(routes_agents._connected_providers) and the skills they can pick from.

**What counts as a need.** Only gmail, calendar and gdrive need a
connection of the person's own (routes_agents._TOKEN_TABLES); documents,
excel, memory, schedules, code, video and the account tool work for
everyone. Eighteen skills name only `server:mcp-proxy`. Read one by one on
2026-11-04: the ten in TRACKER_SKILLS read a task tracker, the other eight
need only web search, which is a shared server and so needs nothing.

**A task tracker is the person's own** Trello, GitHub, ClickUp or Jira. The
shared proxy servers hold the team's boards; the ask is what THIS person
connected. The list and the label it is written into are kept honest by
test_the_tracker_label_names_every_tracker_that_satisfies_it: a tracker
added to one and not the other reads as not counting.
"""
from __future__ import annotations

GOOGLE = ("gmail", "calendar", "gdrive")
TRACKERS = ("trello", "github", "clickup", "jira")
TRACKER = "tracker"

TRACKER_SKILLS = frozenset({
    "backlog-groom", "blocker-report", "daily-standup", "delegate-this",
    "estimate-check", "meeting-to-tasks", "risk-register", "sprint-health",
    "task-from-conversation", "weekly-plan",
})

#: The order apps are listed in, everywhere, so a message reads the same
#: twice.
ORDER = ("gmail", "calendar", "gdrive", TRACKER)

LABELS = {"gmail": "Gmail", "calendar": "Google Calendar",
          "gdrive": "Google Drive",
          TRACKER: "a task tracker (Trello, GitHub, ClickUp or Jira)"}

#: The words on the button. The tracker's full label is too long for one.
BUTTON = {"gmail": "Connect Gmail", "calendar": "Connect Google Calendar",
          "gdrive": "Connect Google Drive", TRACKER: "Connect a task tracker"}

#: What `#aiui-connect:<id>` opens. Google apps go straight to their login;
#: Trello has no login to open, so the button opens the Connections panel,
#: where GitHub and ClickUp sit beside it.
CONNECT_ID = {"gmail": "gmail", "calendar": "calendar", "gdrive": "gdrive",
              TRACKER: "trello"}


def needs(skill) -> list:
    """The apps `skill` cannot run without, in ORDER."""
    if not isinstance(skill, dict):
        return []
    tools = set(skill.get("tools") or [])
    out = [app for app in GOOGLE if app in tools]
    if skill.get("name") in TRACKER_SKILLS:
        out.append(TRACKER)
    return out


def missing(skill, connected) -> list:
    """The apps `skill` needs that are not in `connected`."""
    have = set(connected or ())
    out = []
    for app in needs(skill):
        if app == TRACKER:
            if not any(t in have for t in TRACKERS):
                out.append(app)
        elif app not in have:
            out.append(app)
    return out


def split(names, pool: dict, connected) -> tuple[list, dict]:
    """(ready, gaps) for skill `names`, keeping their order.

    `gaps` is app -> the skills waiting on it. A skill missing two apps is
    listed under both, so connecting either one says what it brings. Names
    not in `pool` are ignored: deciding what is a real skill is not this
    module's job.
    """
    ready, gaps = [], {}
    for name in names or []:
        skill = (pool or {}).get(name)
        if not skill:
            continue
        lacking = missing(skill, connected)
        if not lacking:
            ready.append(name)
        for app in lacking:
            gaps.setdefault(app, []).append(name)
    return ready, gaps


def connect_lines(gaps: dict, kept: bool = False) -> list:
    """Two lines per app: which skills it adds, then the link the main chat
    turns into a Connect button (integrations-ui.js, wireAiuiConnectLink).

    `kept` is for skills the person named: they stay on the agent, so the
    line says connecting makes them work rather than adds them.
    """
    out = []
    for app in ORDER:
        names = (gaps or {}).get(app)
        if not names:
            continue
        verb = "so these work:" if kept else "to add:"
        out.append("Connect %s %s %s" % (LABELS[app], verb, ", ".join(names)))
        out.append("[%s](#aiui-connect:%s)" % (BUTTON[app], CONNECT_ID[app]))
    return out


def needs_connect(gaps: dict) -> list:
    """The same facts as data, for a page that draws its own buttons."""
    return [{"app": app, "label": LABELS[app], "skills": list(gaps[app]),
             "connect": "#aiui-connect:" + CONNECT_ID[app],
             "button": BUTTON[app]}
            for app in ORDER if (gaps or {}).get(app)]


# --- "which skills should I use?" (2026-11-04) -------------------------------

#: What a ready skill is listed under: the first app it needs, in ORDER.
READY_LABELS = {"gmail": "Gmail", "calendar": "Google Calendar",
                "gdrive": "Google Drive", TRACKER: "Your task tracker"}

#: Names shown per group before "and N more". A reply the person reads, so
#: a group is a few examples rather than a second catalogue.
GROUP_CAP = 8


def overview(pool: dict, connected) -> dict:
    """What this person's connections make ready, and what connecting more
    would add. A skill needing nothing is only counted: those work for
    everyone and are not what connections change."""
    ready, waiting, free = {}, {}, 0
    for name in sorted(pool or {}):
        skill = pool[name]
        wants = needs(skill)
        if not wants:
            free += 1
            continue
        lacking = missing(skill, connected)
        if not lacking:
            ready.setdefault(wants[0], []).append(name)
        for app in lacking:
            waiting.setdefault(app, []).append(name)
    return {
        "ready": [{"app": a, "label": READY_LABELS[a], "skills": ready[a]}
                  for a in ORDER if ready.get(a)],
        "connect": needs_connect(waiting),
        "no_connection": free,
    }


def _some(names: list) -> str:
    shown = ", ".join(names[:GROUP_CAP])
    rest = len(names) - GROUP_CAP
    return shown + (" and %d more" % rest if rest > 0 else "")


def overview_text(ov: dict, mine=None) -> str:
    """The reply itself. The `[Connect X](#aiui-connect:x)` lines become
    buttons in the main chat (integrations-ui.js, wireAiuiConnectLink)."""
    lines = []
    if ov.get("ready"):
        lines.append("Skills that work with what you have connected:")
        lines += ["%s: %s" % (g["label"], _some(g["skills"])) for g in ov["ready"]]
    else:
        lines.append("Nothing you have connected unlocks a skill yet.")
    if mine:
        lines += ["", "Your own skills: %s" % _some(list(mine))]
    if ov.get("connect"):
        lines += ["", "Connect more to add skills:"]
        for g in ov["connect"]:
            lines.append("%s would add: %s" % (g["label"][0].upper() + g["label"][1:],
                                               _some(g["skills"])))
            lines.append("[%s](%s)" % (BUTTON[g["app"]], g["connect"]))
    free = ov.get("no_connection") or 0
    if free:
        lines += ["", "%d more skill%s need%s nothing connected." % (
            free, "" if free == 1 else "s", "s" if free == 1 else "")]
    lines += ["", "Ask me to add any of these to an agent."]
    return "\n".join(lines)


#: Words that mean an answer is talking about an app, per app. The tracker is
#: named by any of the three as often as by the word itself.
MENTIONS = {
    "gmail": ("gmail",),
    "calendar": ("calendar",),
    "gdrive": ("drive",),
    TRACKER: ("tracker", "trello", "clickup", "github"),
}


def missing_links(answer: str, connect: list) -> list:
    """The `[Connect X](#aiui-connect:x)` lines an answer about skills should
    carry and does not: for each app this person has not connected
    (`connect`, as needs_connect gives it) that the answer names while
    talking about connecting. In the order given.

    Decided here, not by the model: live on 2026-11-04 the main chat's model
    read suggest_skills, then wrote "There's a Connect button above" and
    left the link out, so there was no button anywhere."""
    text = str(answer or "").lower()
    if "connect" not in text:
        return []
    out = []
    for need in connect or []:
        href = need.get("connect") or ""
        words = MENTIONS.get(need.get("app"), ())
        if href and href.lower() not in text and any(w in text for w in words):
            out.append("[%s](%s)" % (need.get("button") or "Connect", href))
    return out
