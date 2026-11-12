# Triage agent: design (2026-11-12)

What Lukas asked for at the end of the 2026-11-12 call ("that's like the
biggest task"), and how it is built. The user asked for it to be built in
full with no further questions.

## What he asked for

> "I would want the decisions API to see all the skills, all the
> integrations ... let's say that I don't have Airtable ... and I say, I want
> to scrape and find a bunch of customers and save them somewhere ... I would
> want the triage agent to suggest me to create the Airtable account."

> "If it says every 8 a.m., read my email, it should know that it's going to
> use cron jobs and it's going to use Gmail integration."

> "Even though it's not integrated yet, seeing all of those possible
> connections, and recommending the right one to the end user."

> "Either you can have it cheap, self-hostable n8n, or you can pay more and
> have it hosted by Zapier. Give them the choice, what's the pros and cons."

> "I have this website ... I want to have it stored and versioned ... I would
> want it to recommend the GitHub integration ... even if they've never heard
> about GitHub."

"Decisions API" is Jev (`agent_decider`, `agent_jev`), as the 2026-11-10
design already names it. "Triage agent" is his name for Jev seeing every
integration and feature and recommending the right one.

## What exists

- On Auto, every message is asked two Jev questions side by side
  (`routes_agent_turn._route_chat`): is it one agent's (`_jev_decision`), and
  which tools does the assistant need (`_tool_pick`). The second already
  covers the platform's features: schedules, automations, the App Builder
  (`code`), agents, video, documents, and the connected apps behind
  `server:mcp-proxy`.
- It only offers tools this person can use. An app they have not connected is
  invisible to it, so nothing ever says "connect Airtable for this".
- `skill_fit.py` already turns a missing connection into a Connect button
  (`[Connect X](#aiui-connect:x)`, drawn by `integrations-ui.js`), but only for
  skills.

## Design

**One more Jev question, asked beside the other two.** `agent_jev.pick_apps`
asks one yes/no per app in `triage.APPS`, every app the platform can connect
(Gmail, Google Calendar, Google Drive, Airtable, HubSpot, GitHub, ClickUp,
Trello, Notion, n8n, Zapier), connected or not: "to do what the person wants,
would this app be a good fit, even if they did not name it?" Same shape as
`pick_tools` and `pick_skills`: one call, the context of the conversation,
one row in `tasks.jev_check` (purpose `app_pick`), its own cut-off in `CUTS`.
Jev unavailable means no triage and the chat behaves exactly as before.

**A plan, not a guess.** `triage.plan` joins Jev's picks with the person's
real connections (`routes_agents._connected_providers`, the same reading the
Connect panel uses) and the features the tool pick chose. At most three apps,
best first; an app in a choice group (n8n and Zapier) brings the other one
with it, so the person sees the choice.

**The assistant answers with the plan in front of it.** When any picked app
is not connected, the assistant runs even if no tool was picked (it used to
run only with a tool). Its brief gets a block saying, per app: connected or
not, what IO can do with it, what IO cannot do with it yet, and for a choice
group, the pros and cons of each. It is told to recommend the best fit in a
sentence, to say plainly what it cannot do, and that the Connect buttons are
added under its answer.

**The buttons are the service's, not the model's.** After the turn, every
recommended app that is not connected gets its Connect button under the
answer, and a one-line "Recommended: X, because ..." when the answer never
named it. Same reason as `_with_connect_links`: on 2026-11-04 the model said
"there's a Connect button above" and left the link out. A turn waiting for
approval is left alone.

## Honesty rules (the "no guessing" part)

Every "IO can" line in `triage.APPS` names the tools it rests on, and a test
fails if any of them does not exist in `mytools.PROVIDER_TOOLS` (or, for the
Google apps, in `agent_jev.TOOL_NOTES`). What exists on 2026-11-12:

| App | IO can | IO cannot yet |
|---|---|---|
| Airtable | read bases, tables and rows | add or change rows |
| HubSpot | list contacts, deals, companies; add a contact | change or delete them |
| GitHub | read repos, branch, write a file as a commit, open a PR, issues | create a repository |
| n8n | list workflows, read one, see runs | create or change workflows |
| Zapier | send data to a Zap, which starts it | create a Zap |
| Notion | search and read pages and database rows | write pages |

So "find customers and save them somewhere" honestly recommends Airtable
(where they keep the list, readable by IO) and HubSpot (where IO can add each
contact), rather than promising that IO writes rows into Airtable.

## Calibration

The cut-off is measured, not chosen: `scripts/jev_checks_calibrate.py` gains
labelled app cases (Lukas's own examples, ordinary questions that must
recommend nothing), run against the live Jev in the tasks container through
the same request builder production uses. Rule fixed before the run: a wrong
recommendation (an app on a message that needs none, or a wrong app) is worse
than a missed one, so the cut is the lowest with zero wrong picks in every
run, plus one step of margin. No clean cut: the check ships off.

## Measured (2026-11-12, jev-1.13.0, live tasks container)

Calibration, 17 messages x 2 runs, $0.002: at 0.90 no wrong pick and no
missed need in either run; 0.85 had one wrong pick, 0.75 four. Ordinary
questions (a joke, a poem, "thanks", a capital city) topped out at 0.62.

One finding changed the design. For "every 8am read my email and send me a
summary" Jev scored n8n 0.96 and Zapier 0.90 beside Gmail 0.92, while the
tool pick chose schedules 0.78. Lukas said that case is "cron jobs and Gmail",
so `plan` drops n8n and Zapier when schedules is picked, unless the person
named one. "I need an automation workflow that connects my apps" picks no
schedules, so the n8n vs Zapier choice stays.

Dry run of the new code from a temp folder in the tasks container (live Jev,
live tool pick, live connection read; production files untouched), for an
account with nothing connected:

| Message | Tool pick | Recommended |
|---|---|---|
| find customers and save them somewhere | none | Airtable 0.94 |
| every 8am read my email ... | account, gmail, schedules | Gmail (n8n, Zapier dropped) |
| landing page, keep every version ... | code | GitHub 0.91 |
| I need an automation workflow ... | none | n8n 0.97, Zapier 0.97 |
| I need something to track my to-dos | none | Notion 0.96, Trello 0.96 |
| what is the capital of Australia | none | nothing; the free model answers as before |

GitHub on the versioning ask: Lukas's own wording scored 0.94 to 0.95 in 4 of
4 tries, a shorter paraphrase 0.89 to 0.91, so a terse phrasing can fall just
under the cut. The next app scored under 0.45 every time.

## Not in this round

- Discord and the agents panel: only the main chat (Auto) triages.
- Airtable writes, n8n workflow creation, GitHub repository creation: tools
  that do not exist yet. The plan says so instead of pretending.
- Skills: already recommended from connections by `skill_fit` through the
  skills tool; triage does not duplicate it.
