# Automations

Since 2026-10-27 a person can set up rules of their own, in the platform,
without n8n: when this happens, this agent does this, and the answer goes
there. Every rule belongs to one person and runs with their agents and
their connections.

## Making one

Agents page → **Automation** → under Automations: a name, which agent, what
the agent should do when it happens, and where the answer goes. **Add
automation**. The rule gets its own URL.

- **Answer in the agent's chat**: the answer appears in that agent's
  private conversation, in the office and on the Agents page, under a
  note naming the automation.
- **Answer in my Discord thread**: posted to the schedules thread the
  Discord bot keeps for you. Link Discord first, or the run says it could
  not be delivered.
- **Answer only to whoever called**: nothing is posted; the caller reads
  the reply.

## From the main chat

Type it: "when a new lead comes in from my website form, have Ada write a
first reply and add a to-do, and post it to my Discord". The main chat's
assistant picks the Automations tool, asks you to confirm, makes the rule
and hands back its URL. "List my automations", "pause the lead rule",
"run the invoice rule now" work the same way. Anything on a timer
("every Monday at nine") is a schedule, and the chat makes those too.

The tool is `open-webui-functions/automations_tool.py`, installed by
pasting into Workspace → Tools and enabling it on Auto, like the Agent
Builder.

## The URL

```
POST https://ai-ui.coolestdomain.win/api/tasks/hooks/hk_...
```

Anything can call it: a website form, Zapier, Make, n8n, a GitHub webhook,
a phone shortcut, `curl`. The body can be JSON, a form or plain text; with
no body, the query string is used. What was posted is handed to the agent
as data, after the rule's instructions, under a line telling the agent it
is data and not instructions.

The call returns at once with `{"status": "accepted"}` and the agent runs
in the background. Add `?wait=1` to wait for the answer in the reply
(up to seven minutes).

The token in the URL is the secret. **New URL** on the rule retires the
old one at once. **Pause** stops the rule without deleting it; a paused or
unknown URL answers the same 404, so a URL tells nobody which it is.

## What the agent may do

Nobody watches an automated run, so there is nobody to ask. An agent set
to **All** acts; one set to **Ask** or **Read** reads and answers, and says
in the result what it did not do.

## Limits

Twenty rules per person. Two runs at a time per tasks process, the rest
queue. A posted body is read up to 12,000 characters. Each rule keeps its
last five runs, shown on the Agents page.

## Keys

The same panel also makes **keys** for the older way in: an `iok_` key
sent as a bearer token to `POST /api/tasks/agents/run` with an agent name
and a message, for a caller that wants to pick the agent and the message
itself. See `docs/n8n-run-agent.md`.
