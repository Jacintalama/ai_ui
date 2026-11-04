# Skills suggested from what a person has connected (2026-11-04)

## The ask

Lukas, standup 2026-11-03: "I would want the AI to kind of suggest skills
based on the things that the user has connected, to make it more repeatable
or to give the user the expected outcome." Approved shape: both places
(making an agent from the main chat, and asking the main chat which skills
to use), and where a skill needs an app that is not connected, a Connect
button instead of the skill, in the main chat and in the AI agent chat.

## What already exists (measured, not assumed)

1. `routes_agents._connected_providers(email)` returns the person's
   connections: `gmail`, `calendar`, `gdrive` from the token tables, plus
   every provider in `tasks.user_connections` (trello, github, clickup,
   notion, airtable, hubspot, zapier, n8n). Fails toward the empty set.
2. Every built-in skill names its tools in `allowed-tools`. Of those, only
   gmail, calendar and gdrive need a connection (`_TOKEN_TABLES`); documents,
   excel_creator, code, schedules, remember, video, account and the
   dashboard need none.
3. 18 skills say only `server:mcp-proxy`. Read one by one: ten read a task
   tracker (backlog-groom, blocker-report, daily-standup, delegate-this,
   estimate-check, meeting-to-tasks, risk-register, sprint-health,
   task-from-conversation, weekly-plan) and eight need only web search,
   which is shared (competitor-scan, fact-check, numbers-check,
   person-brief, pricing-research, research-and-cite, summarise-a-link,
   vendor-compare).
4. The main chat turns `[Connect Gmail](#aiui-connect:gmail)` in a reply into
   a button (`integrations-ui.js`, `wireAiuiConnectLink`): Google apps open
   their login, anything else opens the Connections panel.
5. The Agents page opens its Connections panel for any click on
   `a[href="#connections"]` (body click handler, `openConnections`).
6. A person's own skills (`user_skills.mine`, `user_skills.merge`) sit
   beside the built-in ones and win on a name clash.

Live 2026-11-04: 2 people have Gmail, Calendar and Drive; 1 has Trello.

## Decisions

1. **Matching is code, not a model.** Free, instant, the same answer twice,
   and testable. The words of the role still choose; connections decide
   which of those can be used now.
2. **A task tracker means the person's own Trello, GitHub or ClickUp.** The
   shared proxy servers are the team's boards, not theirs; "things the user
   has connected" is the ask.
3. **A suggested skill that needs an unconnected app is left out and named
   with a Connect button.** Nothing is saved that would fail when it runs.
   The ready list is topped up from lower-ranked skills that still clear
   the existing floor, so connections change what is offered, not just what
   is removed.
4. **A skill the person named themselves is kept** even if its app is not
   connected (they asked for it), and the preview says what it needs.
5. **Fail closed toward "not connected".** A Connect button nobody needed is
   a nag; a skill that silently cannot run is the failure being fixed.

## Pieces

1. `mcp-servers/tasks/skill_fit.py` (new, pure): `needs(skill)`,
   `missing(skill, connected)`, `split(names, pool, connected)`,
   `connect_lines(gaps)`.
2. `agent_skills.suggest` takes an optional `pool` so a person's own skills
   can be suggested too.
3. `/agents/make` (preview): ready skills on the Skills line, then
   "Connect Gmail to add: inbox-triage, draft-reply" and the Connect link.
   Returns `needs_connect` alongside `skills`.
4. `GET /agents/skills/suggest` (new, signed in): ready skills grouped by
   the connected app that makes them work, the person's own skills, and per
   unconnected app what it would add with a Connect link. `message` is the
   finished text.
5. `agent_builder_tool.suggest_skills` (new method) returns that message;
   `agent_jev.TOOL_NOTES["agent_builder"]` mentions skill questions so Jev
   picks it.
6. `GET /agents/skills/needs?skills=a,b` (new, signed in): which of those
   skills need an app this person has not connected.
7. Agents page: when the chat is switched to one agent, a notice above the
   message box ("inbox-triage needs Gmail.") with a Connect button that
   opens the Connections panel. `agent-chat.js` turns `#aiui-connect:` links
   in a reply into the same button.

## Testing

Pure tests for `skill_fit`; route tests for make, suggest and needs with
connections stubbed; tool tests; a node test of the agent-chat link rewrite
run against the real `agent-chat.js`; the page notice checked in the real
`agents.html` in a browser test. Live check on the server before done:
preview for a person with and without Gmail, the suggest message, the notice
on the Agents page.

## Delivery

PR A: skill_fit, make preview, suggest route, tool, Jev note.
PR B: needs route, Agents page notice, agent-chat link buttons.
Deploy only after approval.
