# Talking to your agents happens in its own panel

Date: 2026-09-07
Status: approved, not yet implemented

## The problem

The previous attempt, `2026-09-04-agents-take-turns-design.md`, is rolled back.
It tried to make each agent's reply its own message inside Open WebUI's chat by
naming the remaining agents in an HTML comment appended to the pipe's reply,
then having the page run each one and write it into the chat tree.

It failed in production the same night it shipped. Two of its premises were
wrong:

1. **An HTML comment does not survive markdown rendering invisibly.** Open WebUI
   escapes it and prints it, so the raw `<!-- aiui:turns ... -->` marker was
   visible in the chat.
2. **Open WebUI renders `message.output[0].content[0].text`, not
   `message.content`.** The page cleaned `content`, and the live browser test
   asserted on `content`, so the test passed while the screen showed the marker
   and a stray `Ada:` label.

The rollback reverted the two pipe rows, so the feature is off. What is still
deployed and harmless: `POST /agents/speak`, migration 046
(`tasks.agent_turn_claim`), and the rewritten `integrations-ui.js`.

The deeper problem is not either bug. It is that we were borrowing Open WebUI's
chat to do something it was not built for: smuggling state through rendered
text, writing into a message tree we do not own, forcing a redraw by navigating,
and racing another tab over one chat record. Each of those is a separate way to
fail and none of them is necessary.

## What we are building

A **round table** panel on the AI Agents page. You pick which of your agents are
in the room. Every message you send gets an answer from each of them, in turn,
each in its own bubble, arriving live as it lands.

We draw the bubbles, so a reply being its own message is not a trick. It is just
what the page renders. There is no marker, no message tree, no navigation, and
no second tab writing into the same record.

The main chat is not touched and keeps working exactly as it does now.

## Where it lives

A panel on `/tasks/agents` (`main.py:212`, serving `static/agents.html`), to the
right of the agent cards.

That space is already empty. The page wrapper is `max-width: 1640px`
(`static/agents.html:54`) while the card grid is capped at `max-width: 792px`
(`:264`, widening to 1188px above 1800px, `:265`). So the panel occupies room
the layout already leaves unused rather than taking width from the cards. Below
the wide breakpoint the panel drops underneath them.

The panel contains a row of chips for who is in the room, the thread, a
composer, and a list of saved conversations.

It is part of that page, not an iframe. But `agents.html` is already 1770 lines,
so the panel's styles and script go in their own files under `static/`, included
by `agents.html`, rather than growing that one further.

## How a round runs

The shape is copied from `routes_fusion_page.py`, which runs this in production
today for the Fusion chat page.

1. `POST /tasks/agents/chat/send` appends your message to the conversation and
   returns your bubble plus an empty assistant area.
2. The browser opens `GET /tasks/agents/chat/stream`.
3. The server walks the room in order, calling `_turn_for`
   (`routes_agent_turn.py:474`) once per agent, and pushes each answer as its
   own event the moment it lands.

`_turn_for` is the right seam because it already applies the agent's access
level, strips speaker labels out of the history it feeds the model, records the
run in `tasks.agent_run`, and never raises, so one agent blowing up cannot take
the round down. We call it in process, the way the Fusion page calls
`fusion_engine`, not over HTTP.

**Agents run one at a time, never in parallel.** That is already the rule in
`/agents/chat` and the reason is this box has 3.8GB of RAM.

Two constraints inherited from Fusion rather than rediscovered:

- **`EventSource` cannot send headers.** The stream authenticates on the
  same-origin Open WebUI cookie; the form posts carry the bearer token from
  `localStorage` (`static/fusion.html:388`).
- **The stream must only answer an unanswered message.** A browser reconnects an
  `EventSource` on its own, and without this guard the reconnect re-runs the
  whole round: an infinite loop that costs real money. Fusion claims the turn
  before its first `await`, by appending the assistant placeholder, so a
  concurrent or reconnecting stream fails the check. We do the same.

## Each agent answers on its own

The history is built **once, before the round starts**, and every agent in the
room receives that same list. Ada's answer from this round is not in Mia's
input.

This is deliberate and it is the one rule most likely to be quietly broken by a
later change. When agents were fed each other's labelled replies, the model
learned the format and began inventing whole exchanges between agents that never
happened. `_turn_for`'s docstring records that incident. Independent inputs mean
two agents may say similar things; that is the accepted cost.

## Approvals

An agent that wants to run a real tool can stop and ask. In that case:

- Its bubble shows the question with Yes and No.
- **The round continues to the next agent.** This matches the existing policy in
  `routes_agent_turn.py:534`, which pauses only the agent that asked.
  Withholding the rest used to drop every other addressed agent for good.

The pending payload (`_pending_payload`, `routes_agent_turn.py:122`) carries the
held conversation and the user's email. Neither goes to the browser. The server
holds it against this conversation and that agent; the browser receives only the
tool name and arguments, the bounded shape `_pending_for_page`
(`routes_agents.py:495`) already builds, and sends back only an id and a yes or
no.

Answering calls the resume path (`routes_agent_turn.py:183`) in process. That
path **re-reads the agent's access level** rather than trusting it from when the
question was asked, so turning an agent down to read only after it asked means
it does not run. A refusal still appends a tool result, because every held
`tool_call` needs a matching tool message before the next completion.

An approval that is never answered is not a failure state. It sits in the
conversation until answered or until the conversation is deleted. That is why
the held payload is a column on the conversation row (`pending`) and not only an
in-memory value: a service restart must not turn an unanswered question into a
dead button.

## Storage

A new table, mirroring `tasks.fusion_chats` (`migrations/032_fusion_chats.sql`):

```sql
CREATE TABLE IF NOT EXISTS tasks.agent_chats (
  id         TEXT PRIMARY KEY,
  user_email TEXT NOT NULL,
  title      TEXT NOT NULL DEFAULT 'New chat',
  messages   JSONB NOT NULL DEFAULT '[]'::jsonb,
  room       JSONB NOT NULL DEFAULT '[]'::jsonb,
  pending    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_chats_user_updated
  ON tasks.agent_chats (user_email, updated_at DESC);
```

Next free number is 047. `db.py` re-runs every migration on startup, so it must
be idempotent, which the `IF NOT EXISTS` form is.

`messages` and `room` are JSONB because a conversation is only ever read and
written as a unit, the same reasoning as 032.

**Every read and write is scoped by `user_email`.** Knowing a conversation id is
never enough to reach it. This is the rule `_save_chat` and `_load_chat` already
follow in `routes_fusion_page.py`.

Nothing in this feature reads or writes Open WebUI's `chat` table.

## What we are designing against

- **A reconnecting stream re-running a paid round.** Handled by the
  unanswered-message guard above.
- **Two tabs on the same conversation.** The server owns the round, so the
  second tab's stream finds no unanswered message and closes. Note this is a
  different mechanism from `tasks.agent_turn_claim`, which exists to referee two
  Open WebUI tabs and is not needed here.
- **An agent that hangs.** Mostly already handled: `_turn_for` never raises, and
  a turn is bounded by `CHANNEL_HTTP_TIMEOUT_SECONDS = 60` per completion with
  `CHANNEL_MAX_TOOL_ITERATIONS = 3` (`agent_runner.py:53`). So a stuck agent
  yields a failure sentence in its own bubble and the round moves on. What is
  not bounded is the round as a whole: three agents each doing tool work can
  hold the stream open for minutes. The panel must therefore show which agent is
  currently working, so a slow round reads as slow rather than as broken.
- **A room that names an agent since deleted.** Skip it and say so once, rather
  than failing the round.

## How this gets verified

Unit tests for: round order, that every agent received identical history, the
approve path, the refuse path, the reconnect guard, and per-user scoping on
every query.

Then a live check on the real site that asserts **on the rendered page**, plus a
screenshot that a person looks at. The previous attempt shipped a live test that
passed against stored data while the screen was wrong. Asserting on what the DOM
actually shows is the specific correction, and it is not optional here.

## Out of scope

- Attaching a file to a message.
- A Chat button on each agent card.
- Agents reading each other's answers.
- Any change to the main chat, the pipes, or `/agents/speak`.
- A synthesis or summary of the round.

## Reused, already deployed and working

- `_turn_for` and the resume path in `routes_agent_turn.py`.
- The agent list and access rules behind `/agents`.
- `routes_fusion_page.py` and `static/fusion.html` as the working pattern for a
  dedicated chat page with streaming and saved conversations.
