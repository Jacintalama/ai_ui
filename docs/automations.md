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

## When an email arrives

Instead of a URL, a rule can start when an email arrives in your connected
Gmail. Choose **Start it when an email arrives** and say which emails:

| Box | What it means |
|---|---|
| From | only mail from this address |
| Subject contains | only mail whose subject contains this |
| Unread only | only mail you have not read |
| A Gmail search of your own | any Gmail search, used exactly as written |

The boxes become a Gmail search, so anything Gmail understands works:
`from:boss@example.com is:unread`, `from:a@b.c OR from:d@e.f`,
`has:attachment subject:"invoice"`. Matching is Gmail's own, not ours.

**You must say which emails.** A rule with no filter would match every
email you get, and this trigger runs the agent once per message.

**Adding a rule never fires it on your old email.** It starts looking from
the moment you create it. It then looks once a minute, and only at mail
that arrived since it last looked.

**At most five emails start a rule in one minute.** If more arrive, the
rest are skipped rather than queued, and the rule moves on: a flood must
not turn into fifty agent turns. The skip is recorded.

The agent is given the email's sender, subject, date and snippet, plus its
id and thread id. It is not given the body: an agent with the Gmail tool
can read the full message itself, and reply on the right thread.

The rule shows when it **last looked**, so you can see it is alive, and
says so if it cannot look any more, which is usually a disconnected Google
account. A rule that has quietly stopped looking otherwise looks exactly
like a rule nobody has emailed.

Only Gmail for now. Calendar and Drive are the same shape and can follow.

## What the agent may do

An agent set to **All** acts. One set to **Read** reads and answers, and
says in the result what it did not do. One set to **Ask** asks, and the
question is written down so it can be answered from anywhere.

## Approvals from anywhere

When an agent on Ask stops before sending, creating or changing
something, the question gets an id and waits up to a day. Answer it:

- On the Agents page under **Automation**, at the top, with Yes or No.
- In the main chat, with a bare "yes" or "no" when nothing else is
  waiting in that chat. If more than one question waits, the chat lists
  them and you answer on the page.

Whoever answers first, the agent carries on exactly where it stopped,
and the result goes where the question came from: the automation's own
delivery, or the agent's conversation in the office for a question born
in the main chat.

**Standing rules** answer the usual questions before they are asked. On
the same panel: allow or deny a tool, always or only when the call
mentions some text. "Allow send_email when it contains @yourcompany.com",
"deny delete_*". Deny wins over allow. A matching rule answers inside the
run, and the result notes what a denying rule stopped.

## Limits

Twenty rules per person. Two runs at a time per tasks process, the rest
queue. A posted body is read up to 12,000 characters. Each rule keeps its
last five runs, shown on the Agents page. An email rule looks once a
minute and starts on at most five emails per look.

## Keys

The same panel also makes **keys** for the older way in: an `iok_` key
sent as a bearer token to `POST /api/tasks/agents/run` with an agent name
and a message, for a caller that wants to pick the agent and the message
itself. See `docs/n8n-run-agent.md`.

## Events out

Give a URL on the same panel, under **Events out**, and the platform
POSTs there when something of yours happens:

| Event | When |
|---|---|
| `build.finished` | an App Builder build or enhance ended |
| `schedule.finished` | a scheduled run ended |
| `automation.finished` | an automation ran: done, failed or waiting |
| `approval.requested` | an agent stopped to ask |
| `approval.decided` | a question was answered |
| `minutes.taken` | a meeting left minutes behind |

Each post is JSON, `{"event", "at", "id", "data"}`, with the header
`X-IO-Event` naming the event and `X-IO-Signature` carrying
`sha256=<HMAC-SHA256 of the body>` under the hook's secret, shown once
when the hook is made. Three tries on a server error; a client error is
not retried. The last result shows on the hook. **Send a test** posts a
test event now. Five hooks per person. The URL must be public, like an
automation's callback.

In n8n: a Webhook node, then an IF on `{{$json.event}}`.
