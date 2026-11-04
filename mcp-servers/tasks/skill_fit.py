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

**A task tracker is the person's own** Trello, GitHub or ClickUp. The shared
proxy servers hold the team's boards; the ask is what THIS person connected.
"""
from __future__ import annotations

GOOGLE = ("gmail", "calendar", "gdrive")
TRACKERS = ("trello", "github", "clickup")
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
          TRACKER: "a task tracker (Trello, GitHub or ClickUp)"}

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
             "connect": "#aiui-connect:" + CONNECT_ID[app]}
            for app in ORDER if (gaps or {}).get(app)]
