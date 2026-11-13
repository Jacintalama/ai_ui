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
    App("linkedin", "LinkedIn",
        "posting to LinkedIn: sharing an update, an article or a link "
        "with your professional network",
        "post an update or a link on LinkedIn as you, publicly or to your "
        "connections only",
        ("create_post",),
        # LinkedIn's open permissions are these and no more. Everything
        # else is partner-gated, and saying so is the difference between
        # a person connecting it for the right reason and connecting it
        # expecting a feed reader.
        cannot="read your feed, your connections, anybody's profile, a "
               "company page or any analytics",
        says=("linkedin",)),
    App("dropbox", "Dropbox",
        "cloud storage for files and folders: finding a file, seeing what "
        "is in a folder, when something was last changed",
        "list a folder, search your files by name and read one file's "
        "details",
        ("list_folder", "search_files", "get_metadata"),
        # Read only on purpose, and the scopes on the consent screen say
        # so too. Upload and share links are each their own card.
        cannot="read the contents of a file, download it, upload, change "
               "or delete anything, or make a share link",
        says=("dropbox",)),
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


@dataclass(frozen=True)
class Platform:
    """Something AIUI does itself, with no connection: picked by Jev in the
    same call as the apps, recommended as the straightforward way, and said
    by the service under the answer (`how`), because the model left alone
    suggests whatever host it read about."""
    id: str
    label: str
    note: str
    how: str
    #: Words that mean the answer already said it.
    says: tuple = ()


#: Lukas, 2026-11-13: "we can deploy the application if they build it, so it
#: wouldn't need to recommend some place to deploy the application, it should
#: just recommend the most straightforward one. But see that there is a
#: possibility to deploy in Vercel." Publishing is the Publish button in the
#: App Builder (routes_projects.publish_app); Deploy to Vercel is in the same
#: window (routes_vercel.py, static/integration-docs.html).
_PLATFORM = (
    Platform("publish", "Publish",
             "putting a website or app they built here in the App Builder "
             "online so other people can visit it: publishing or deploying "
             "it, hosting it, making it live, a link to share it, or a "
             "custom domain. Not building a new one or changing one, and not "
             "an app made somewhere else",
             "To put it online, open the app in the App Builder (or its "
             "preview) and click Publish: it goes live at its own link "
             "straight away. The same window can deploy it to your own "
             "Vercel account instead, once you connect Vercel there.",
             says=("publish",)),
    # Its own entry: asked about Publish alone, "deploy it to Vercel" scored
    # 0.46 to 0.51 even with the build in the conversation, because Vercel
    # reads as somewhere else. Measured 2026-11-13.
    Platform("vercel", "Deploy to Vercel",
             "a request to deploy or host an app they ALREADY built here in "
             "the App Builder on Vercel: their own Vercel account or a "
             "vercel.app link. Never a request to build, design or change a "
             "site or page, and never an app made somewhere else",
             "To put it on your own Vercel, open the app in the App Builder "
             "(or its preview), click Publish and choose Deploy to your "
             "Vercel account; the first time it asks you to connect Vercel.",
             says=("vercel",)),
)
PLATFORM = {p.id: p for p in _PLATFORM}

#: Skills recommended in one answer.
MAX_SKILLS = 2


def catalogue_ids() -> list:
    """Every id Jev is asked about, in order: the apps, then the platform's
    own features. agent_jev.apps_request numbers its questions by this."""
    return list(APPS) + list(PLATFORM)

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


def plan(picks, connected, tools, text: str = "", skills=None,
         pool=None) -> dict:
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
    plat_ids = [i for i, _s in sorted(((str(i), float(s)) for i, s in picks or []
                                       if str(i) in PLATFORM), key=lambda p: -p[1])]
    # Publish's line already mentions Vercel, so both picked is Publish
    # alone unless they said Vercel ("put it online" scored Publish 0.95 and
    # Vercel 0.87, 2026-11-13).
    if "publish" in plat_ids and "vercel" in plat_ids \
            and "vercel" not in str(text or "").lower():
        plat_ids.remove("vercel")
    platform = [{"id": PLATFORM[i].id, "label": PLATFORM[i].label,
                 "how": PLATFORM[i].how} for i in plat_ids]
    return {"apps": apps, "features": features, "platform": platform,
            "skills": _skills(skills, pool, have)}


def _skills(skills, pool, have) -> list:
    """Skills Jev picked for the message, best first, at most MAX_SKILLS, each
    with the apps it needs that this person has not connected (skill_fit)."""
    import skill_fit
    out = []
    for name, _score in sorted(((str(n), float(s)) for n, s in skills or []),
                               key=lambda p: -p[1]):
        skill = (pool or {}).get(name)
        if not isinstance(skill, dict) or len(out) >= MAX_SKILLS:
            continue
        out.append({"name": name,
                    "description": " ".join(
                        str(skill.get("description") or "").split())[:240],
                    "missing": skill_fit.missing(skill, have)})
    return out


def _skill_app_label(need: str) -> str:
    import skill_fit
    return skill_fit.LABELS.get(need, need)


def needs_assistant(p) -> bool:
    """True when something must be recommended: an app the person has not
    connected, something the platform does itself, or a ready-made skill.
    Everything else is already handled by the tool pick."""
    return bool(p) and (any(not a["connected"] for a in p.get("apps") or [])
                        or bool(p.get("platform")) or bool(p.get("skills")))


def brief(p) -> str:
    """The block put in front of the assistant: per app, connected or not,
    what IO can and cannot do, and for a choice the case for each side."""
    apps = (p or {}).get("apps") or []
    platform = (p or {}).get("platform") or []
    skills = (p or {}).get("skills") or []
    if not (apps or platform or skills):
        return ""
    lines = ["Separate from the account above: what fits what the person "
             "wants now (decided for this message):"]
    if platform:
        lines.append("The platform does this itself, so recommend it as the "
                     "straightforward way:")
        lines += ["- %s: %s" % (x["label"], x["how"]) for x in platform]
        lines.append("Do not suggest other hosting services or sites.")
    if skills:
        lines.append("Ready-made skills that fit (read one with the skills "
                     "tool and follow its steps):")
        for s in skills:
            line = "- %s: %s" % (s["name"], s["description"])
            if s["missing"]:
                line += " It needs %s connected, which they have not." % (
                    " and ".join(_skill_app_label(a) for a in s["missing"]))
            lines.append(line)
    if apps:
        lines.append("Apps, connected or not:")
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
    # A skill that needs an app the person has not connected: that app's
    # button, the same one skill_fit draws for the skills answers.
    import skill_fit
    for s in (p or {}).get("skills") or []:
        for need in s.get("missing") or []:
            href = CONNECT + skill_fit.CONNECT_ID.get(need, need)
            button = "[%s](%s)" % (skill_fit.BUTTON.get(need, "Connect"), href)
            if href not in low and button not in buttons:
                buttons.append(button)
    # What the platform does itself: how, in the service's words, unless the
    # answer already said it (2026-11-13: left alone, the model suggests
    # whatever host it read about).
    for x in (p or {}).get("platform") or []:
        if not any(w in low for w in PLATFORM[x["id"]].says):
            lines.append(x["how"])
    if not buttons:
        return (answer.rstrip() + "\n\n" + "\n".join(lines)) if lines else answer
    # The buttons go last, together on one line: one paragraph, so they sit
    # side by side. One per line stacked them, touching (live, 2026-11-12).
    return answer.rstrip() + "\n\n" + "\n".join(lines + [" ".join(buttons)])


def already_offered(messages, turns: int = 6, skill_names=()) -> set:
    """Apps whose Connect button one of the assistant's recent replies already
    carries. Measured live 2026-11-12: after Airtable was recommended,
    "thanks!" scored Airtable 0.94 with the exchange as context, so without
    this the button came back under every follow-up. Only the assistant's
    own messages count: a person pasting a link is not an offer made.

    Also the platform's own features whose how-to a reply already gave, and
    any of `skill_names` a reply already named (2026-11-13)."""
    out = set()
    for m in list(messages or [])[-(turns + 1):-1]:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        said = str(m.get("content") or "").lower()
        out |= {i for i in APPS if connect_href(i) in said}
        # A reply that said "publish" at all: in the usual case the model
        # writes "click Publish" itself, the how-line is never added, and
        # matching only that line re-offered Publish on every follow-up
        # (review 2026-11-13).
        out |= {i for i, x in PLATFORM.items()
                if any(w in said for w in x.says)}
    return out | skills_offered(messages, skill_names, turns)


def skills_offered(messages, names, turns: int = 6) -> set:
    """Skill names a recent assistant reply already offered. Strict, because
    a bare substring suppressed `spreadsheet` under any reply about a
    spreadsheet (review 2026-11-13): a hyphenated name as written, or a
    one-word name followed by "skill" or in backticks."""
    out = set()
    for m in list(messages or [])[-(turns + 1):-1]:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        said = str(m.get("content") or "").lower()
        for name in names or ():
            n = str(name).lower()
            if not n:
                continue
            if ("-" in n and n in said) or (n + " skill") in said \
                    or ("`" + n + "`") in said:
                out.add(str(name))
    return out
