"""Which app fits what the person wants, connected or not (2026-11-12).

Lukas, 2026-11-12: "I would want the decisions API to see all the skills,
all the integrations ... Even though it's not integrated yet, seeing all of
those possible connections, and recommending the right one to the end user."
He calls it the triage agent. Jev picks the apps (agent_jev.pick_apps); this
module is everything after that, and it is pure: no network, no database, no
model, so every rule is tested on its own.

**No guessing.** Each app's `can` sentence names the tools it rests on in
`tools`, and tests/test_triage_recommends_apps.py fails when one of them does
not exist. `cannot` says what is missing, so the assistant never promises a
write that no tool can do. Measured 2026-11-12: Airtable, Notion and n8n are
read-only on this platform, GitHub cannot create a repository, Zapier can
only start a Zap that already exists.

Design: docs/plans/2026-11-12-triage-agent-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Apps recommended in one answer. More is a catalogue, not a recommendation.
MAX_APPS = 3

#: What `#aiui-connect:<id>` opens in the main chat (integrations-ui.js): the
#: Google apps go straight to their sign-in, Notion to its OAuth start, and
#: every other id opens the Connections panel, where its card is.
CONNECT = "#aiui-connect:"


@dataclass(frozen=True)
class App:
    id: str
    label: str
    #: What it is for, in the words a person would use. The whole basis on
    #: which Jev picks it, so a goal missing from here is never matched.
    note: str
    #: What IO can do with it once connected. Rests on `tools`.
    can: str
    #: The tools `can` rests on: mytools.PROVIDER_TOOLS names, or for the
    #: Google apps the main chat's tool id itself.
    tools: tuple
    #: What IO cannot do with it yet, said rather than left to be assumed.
    cannot: str = ""
    #: Apps in the same group are alternatives: one picked brings the other,
    #: so the person is shown the choice and not only one side of it.
    group: str = ""
    #: The case for this side of a choice, in a sentence.
    pros: str = ""
    #: Other words an answer uses for it ("your calendar"), so an answer
    #: that already named it is not given a second introduction.
    says: tuple = ()


_APPS = (
    App("gmail", "Gmail",
        "email: reading, searching, drafting or sending email, including "
        "emails to a list of leads or customers",
        "read, search, draft and send email",
        ("gmail",)),
    App("calendar", "Google Calendar",
        "a calendar: events, meetings, appointments and booking time",
        "read the calendar and add, move or delete events",
        ("calendar",), says=("calendar",)),
    App("gdrive", "Google Drive",
        "storing, finding or reading files, documents and spreadsheets",
        "find and read files in Drive",
        ("gdrive",), says=("drive",)),
    App("airtable", "Airtable",
        "a database made of tables, like a spreadsheet, for keeping records: "
        "leads, customers, contacts, orders, inventory, or any list of things "
        "to store, sort and filter",
        "read your bases, tables and rows, make a new table, add rows and "
        "change a row",
        ("list_my_bases", "list_tables", "list_records", "create_table",
         "create_record", "create_records", "update_record"),
        cannot="make a new base, or delete a table or a row"),
    App("hubspot", "HubSpot",
        "a CRM for sales: leads, contacts, companies and deals, and keeping "
        "track of following up with customers",
        "list contacts, deals and companies, and add a new contact",
        ("list_contacts", "list_deals", "list_companies", "create_contact"),
        cannot="change or delete contacts"),
    App("github", "GitHub",
        "keeping the code and files of a website or app stored with every "
        "version kept, going back to an older version, sharing code with "
        "other people, issues and pull requests",
        "read repositories, make a branch, save a file as a commit, open a "
        "pull request, and open or comment on issues",
        ("list_my_repos", "create_branch", "write_file",
         "create_pull_request", "create_issue", "comment_on_issue"),
        cannot="create a new repository"),
    App("clickup", "ClickUp",
        "a project board for tasks and to-dos: creating tasks, assigning "
        "people, moving tasks between columns and tracking a team's work",
        "create and update tasks, assign people and move tasks between "
        "columns",
        ("create_task", "update_task")),
    App("trello", "Trello",
        "a simple board of cards in columns for tasks and to-dos",
        "create, move, assign, comment on and complete cards",
        ("create_card", "update_card", "assign_member_to_card",
         "comment_on_card", "complete_card")),
    App("jira", "Jira",
        "issue tracking for a software team: bugs, stories, epics, a "
        "backlog, sprints and moving work through a workflow of statuses",
        "list your projects, search issues with JQL, read one issue, create "
        "an issue and comment on one",
        ("list_my_projects", "search_issues", "get_issue", "create_issue",
         "comment_on_issue"),
        # Both need a second call to look an id up first: a transition by
        # its id from /issue/{key}/transitions, an assignee by accountId.
        # Until those exist, saying so is the difference between a person
        # checking their board and a person wondering why it did not move.
        cannot="change an issue's status or assignee, or delete anything",
        says=("jira",)),
    App("notion", "Notion",
        "pages and databases for notes, documents, a wiki or to-do lists",
        "search pages and databases, read a page's properties and list a "
        "database's rows",
        ("search", "get_page", "query_database"),
        cannot="read a page's text, or write or change pages"),
    App("n8n", "n8n",
        "automation workflows that connect apps and run steps on their own, "
        "when something happens or on a timer",
        "list your workflows, read one and see its recent runs",
        ("list_my_workflows", "get_workflow", "list_executions"),
        cannot="create or change workflows",
        group="automation",
        pros="Source-available (fair-code) and can be self-hosted, so it "
             "costs only the server it runs on (or a paid n8n Cloud plan); "
             "more control and custom code, but more setup."),
    App("zapier", "Zapier",
        "automation between apps without code, hosted for you: when "
        "something happens in one app, do something in another",
        "send data to a Zap you made, which starts it",
        ("send_to_zap",),
        cannot="create or change Zaps",
        group="automation",
        pros="Fully hosted with nothing to run, the quickest to start and "
             "connects to thousands of apps; the free plan is small and "
             "paid plans cost more as usage grows."),
)

#: Every app the platform can connect, in the order Jev is asked about them.
APPS = {a.id: a for a in _APPS}

#: Said while the assistant works out a recommendation with no tool to run,
#: so the chat is not silent (agent_progress, 2026-10-29: a line only when it
#: is true of this message).
CHOOSING_LINE = "Choosing the right app for this..."

#: The platform's own features, as the main chat's tool pick names them, in a
#: sentence the assistant can repeat. These need no connection: they are what
#: Lukas means by "it should know that it's going to use cron jobs".
FEATURES = {
    "schedules": "Scheduled jobs: runs something for them on a timer, such "
                 "as every day at 8am",
    "automations": "Automations: runs one of their agents when something "
                   "arrives, such as a webhook, a form or a matching email",
    "code": "App Builder: builds and changes websites and apps here, keeping "
            "every version so an older one can be brought back",
    "agent_builder": "AI agents: makes agents or a team of agents for them",
    "video": "Videos: makes short videos",
    "excel_creator": "Spreadsheets: makes an Excel file",
    "documents": "Documents: reads and writes documents",
    "server:mcp-proxy": "Web search and their connected apps",
}


def connect_href(app_id: str) -> str:
    return CONNECT + app_id


def _button(app: App) -> str:
    return "[Connect %s](%s)" % (app.label, connect_href(app.id))


#: The platform's own timer. When the tool pick chose it, the job is the
#: platform's to run, and a third-party automation app is not recommended
#: for it unless the person named one.
TIMER_TOOL = "schedules"
AUTOMATION_GROUP = "automation"


def _named(app: App, text: str) -> bool:
    return app.label.lower() in str(text or "").lower()


def plan(picks, connected, tools, text: str = "") -> dict:
    """What the assistant is told and the buttons are drawn from.

    `picks` is [(app id, score)] from Jev, `connected` the person's
    connections by provider id, `tools` the tool ids the tool pick chose,
    `text` the person's message. Best first, at most MAX_APPS, unknown ids
    dropped, and an app in a group brings the rest of its group straight
    after it.

    A job on a timer is the platform's (Lukas, 2026-11-12: "every 8 a.m.,
    read my email ... it's going to use cron jobs and it's going to use
    Gmail integration"). Measured live for that message: Jev scored n8n
    0.96 and Zapier 0.90 beside Gmail 0.92, while the tool pick chose
    schedules. So with schedules picked, n8n and Zapier are dropped unless
    the person named one of them.
    """
    timer = TIMER_TOOL in (tools or [])
    ranked = sorted(((str(i), float(s)) for i, s in picks or []
                     if str(i) in APPS), key=lambda p: -p[1])
    if timer:
        ranked = [(i, s) for i, s in ranked
                  if APPS[i].group != AUTOMATION_GROUP or _named(APPS[i], text)]
    have = set(connected or ())
    jev = dict(ranked)
    chosen = []
    for app_id, _score in ranked:
        if app_id in chosen:
            continue
        if len(chosen) >= MAX_APPS:
            break
        group = APPS[app_id].group
        # A choice is shown whole even past the cap: one side of it alone
        # is a recommendation pretending to be a comparison.
        chosen += [app_id] + [a.id for a in _APPS if group and a.group == group
                              and a.id != app_id and a.id not in chosen]
    apps = []
    for app_id in chosen:
        a = APPS[app_id]
        apps.append({"id": a.id, "label": a.label,
                     "connected": a.id in have, "can": a.can,
                     "cannot": a.cannot, "group": a.group, "pros": a.pros,
                     "score": jev.get(app_id)})
    features = [FEATURES[t] for t in tools or [] if t in FEATURES]
    return {"apps": apps, "features": features}


def needs_assistant(p) -> bool:
    """True when something must be recommended that the person has not
    connected. Everything else is already handled by the tool pick."""
    return bool(p) and any(not a["connected"] for a in p.get("apps") or [])


def brief(p) -> str:
    """The block put in front of the assistant: per app, connected or not,
    what IO can and cannot do, and for a choice the case for each side."""
    apps = (p or {}).get("apps") or []
    if not apps:
        return ""
    lines = ["Separate from the account above: apps that fit what the person "
             "wants now, connected or not (decided for this message):"]
    for a in apps:
        state = "connected" if a["connected"] else "not connected"
        line = "- %s (%s). IO can %s." % (a["label"], state, a["can"])
        if a["cannot"]:
            line += (" IO cannot %s yet, so do not offer to %s with it, "
                     "even once it is connected." % (a["cannot"], a["cannot"]))
        if a["pros"]:
            line += " " + a["pros"]
        lines.append(line)
    features = (p or {}).get("features") or []
    if features:
        lines.append("Platform features that need no connection:")
        lines += ["- " + f for f in features]
    lines.append(
        "Recommend the best fit for what they asked in a sentence and say "
        "why, even if they never heard of it. When two apps are a choice, "
        "give the case for each in a sentence and let them choose. If an app "
        "is not connected, tell them to connect it: a Connect button is "
        "added under your answer, so do not write a link yourself. Never "
        "say IO can do something listed as what it cannot do yet.")
    return "\n".join(lines)


def with_buttons(answer: str, p) -> str:
    """`answer` with a Connect button for every recommended app that is not
    connected, each at most once, and a one-line introduction for one the
    answer never named. Measured 2026-11-04: the model wrote "there's a
    Connect button above" and left the link out, so the service adds it.

    An app with a limit always gets the limit said, named or not. On the live
    site 2026-11-12 the model, with "IO cannot add or change rows yet" in its
    brief, still wrote "I'll be able to write rows into it once it is". The
    truth under a recommendation is the service's to state, not the model's.
    """
    answer = str(answer or "")
    low = answer.lower()
    lines, buttons = [], []
    for a in (p or {}).get("apps") or []:
        if a["connected"]:
            continue
        app = APPS[a["id"]]
        if connect_href(app.id) in low:
            continue
        if not any(w in low for w in (app.label.lower(),) + app.says):
            line = "Recommended: %s, so IO can %s" % (app.label, app.can)
            if app.cannot:
                line += " (it cannot %s yet)" % app.cannot
            lines.append(line + ".")
        elif app.cannot:
            # The LIMIT alone, because the answer already named the app and
            # described it. Measured on the live site 2026-11-13, two real
            # turns about Jira: the model wrote what it would be able to do
            # and the service then appended the same list in its own words,
            # the same thing twice in two voices. What the model gets wrong
            # is the limit, which is why this branch exists.
            lines.append("%s cannot %s yet." % (app.label, app.cannot))
        buttons.append(_button(app))
    if not buttons:
        return answer
    # The buttons go last, together on one line: one paragraph, so they sit
    # side by side. One per line stacked them, touching (live, 2026-11-12).
    return answer.rstrip() + "\n\n" + "\n".join(lines + [" ".join(buttons)])


def already_offered(messages, turns: int = 6) -> set:
    """Apps whose Connect button one of the assistant's recent replies already
    carries. Measured live 2026-11-12: after Airtable was recommended,
    "thanks!" scored Airtable 0.94 with the exchange as context, so without
    this the button came back under every follow-up. Only the assistant's
    own messages count: a person pasting a link is not an offer made."""
    out = set()
    for m in list(messages or [])[-(turns + 1):-1]:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        said = str(m.get("content") or "").lower()
        out |= {i for i in APPS if connect_href(i) in said}
    return out
