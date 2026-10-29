# An email can start an automation (2026-10-29)

## Why now

`automations.TRIGGERS` is `frozenset({TRIGGER_WEBHOOK})` and the code
answers "The only trigger today is a webhook." Migration 060 already left
`trigger TEXT NOT NULL DEFAULT 'webhook'` with the comment "an email trigger
comes next", so the row has been waiting for this since 2026-10-27.

It is worth doing **now** rather than earlier because it stands on per-account
Google tokens being trustworthy, and they were not until this morning:

- PR #49 keyed every token row by the account's email address and added a
  `CHECK` enforcing it. Before that, a poller walking "accounts with a
  `gmail_tokens` row" would have walked rows keyed by Open WebUI user id that
  no read would ever match.
- PR #50 made a connect belong to whoever actually signed in. Before that, a
  token row could belong to somebody else's Google account, so a poller would
  have read a stranger's mailbox and handed it to this person's agent.

## What already works and is not being rebuilt

`automation_runner.fire(automation, payload, agent_name)` is the whole firing
path and is trigger-agnostic: it builds the message with
`automations.message_for`, runs the turn on `SURFACE_AUTOMATION` through the
`_slots` semaphore, holds an approval if the agent stops to ask, delivers to
chat/Discord/none, records the run, and emits `automation.finished`. It never
raises.

So the email trigger is **only** a thing that decides *when* to call `fire`
and *with what payload*. No new runner, no new delivery, no new run table.

## The shape

### One new table, one cursor per rule

```sql
tasks.automation_email_cursor (
    automation_id  UUID PRIMARY KEY,
    user_email     TEXT NOT NULL,
    after_epoch    BIGINT NOT NULL,     -- Gmail internalDate seconds
    seen_ids       TEXT NOT NULL,       -- recent message ids, newest first
    checked_at     TIMESTAMPTZ,
    last_error     TEXT NOT NULL DEFAULT ''
)
```

Per rule rather than per account, because each rule has its own Gmail query
and so its own idea of what it has already seen. With `MAX_PER_PERSON = 20`
and six accounts the row count is trivial.

**`after_epoch` starts at the moment the rule is created, never at zero.**
Otherwise making a rule fires it on every email in the mailbox's history,
which with one agent turn per message is both a bill and an inbox full of
replies. This is the single most important line in the plan.

**`seen_ids` exists because `after:` alone is not enough.** Gmail's `after:`
is inclusive and its timestamps are the server's, not ours, so the same
message can come back on the next tick. We query with a small overlap on
purpose (`after_epoch - OVERLAP`) so a message arriving in the same second as
the cursor is not lost, and then drop anything whose id we have already fired
on. Belt and braces, in the direction that costs a duplicate query rather
than a missed email.

### Matching is Gmail's job, not ours

The rule stores a Gmail query string (`trigger_query`), e.g.
`from:boss@example.com is:unread`. The poller sends
`trigger_query + " after:<epoch>"` to `mcp-gmail`'s existing
`/gmail_search_emails`.

Reimplementing from/subject/label matching locally would be a worse version
of something Gmail already does well, and would drift. The UI offers plain
boxes (from, subject contains, unread only) that compose into the query, and
an "advanced" field for anyone who wants to write Gmail syntax directly.

**A query is required.** A rule with an empty query matches every email and
would run an agent on all of it. `problem_with` refuses it.

### What the agent is handed

The message metadata, not the body: subject, from, date, snippet. The agent
has the Gmail tool and can read the full message itself if it needs to, which
is cheaper than hauling every body through the poller and is the same
division of labour the rest of the platform uses.

### Caps, because this spends money per email

- At most `EMAIL_BURST` (5) messages fired per rule per tick, oldest first.
  Beyond that the cursor still advances and a note is recorded, so a flood
  cannot queue fifty agent turns. The App Builder has already been stopped
  dead once by a 402 from OpenRouter; a trigger that fires per email is
  exactly the shape that does that again.
- The existing `_slots` semaphore already bounds concurrency at 2.
- One tick a minute, on the same heartbeat the scheduler uses.

### One small change to mcp-gmail

`/gmail_search_emails` returns the `Date` **header**, which is written by the
sender and can be wrong or absent. A cursor cannot be built on that. The
service already fetches `format=metadata`, whose response carries Gmail's own
authoritative `internalDate`, and simply does not pass it through. Add
`internal_date` to each returned email. Additive, so nothing that reads the
response today notices.

## Pieces, in order

1. **`email_trigger.py`** — the pure logic: compose a query from the boxes,
   build the `after:` clause with its overlap, decide which returned messages
   are new, cap the burst, advance the cursor. No I/O, so it is all testable.
2. **Migration 064** — the cursor table. Idempotent, like every other one.
3. **`automations.py`** — `TRIGGER_EMAIL`, in `TRIGGERS`; `trigger_query` on
   the row; `problem_with` refuses an email rule with no query; the payload
   shape for an email.
4. **mcp-gmail** — `internal_date` passed through.
5. **`email_poller.py`** — the tick: find enabled email rules, search per
   rule as that account, fire the new ones, write the cursor. Never raises,
   every outward call a seam.
6. **`main.py`** — start the loop in `lifespan`, guarded like
   `schedule_tick_loop` so a failure cannot stop the service booting.
7. **The Agents page** — trigger choice on the Automation panel, the filter
   boxes, and "last checked" so a person can see it is alive.
8. **`docs/automations.md`** and `CLAUDE.md`.

## How it gets verified

Unit tests for every pure decision in step 1, which is most of the risk:
first-run-does-not-fire-on-history, a duplicate is not fired twice, a burst
is capped, a missing `internalDate` does not crash a tick.

Then on the box, because a poller is exactly the kind of thing that passes
its tests and never runs: create a rule against my own account, send one
email to it, and watch one run appear with the right trigger text. Then send
three at once and confirm the cap. Then restart `tasks` and confirm the
cursor survived and nothing re-fired.

## Open, and deliberately decided rather than asked

- **Only Gmail.** Calendar and Drive triggers are the same shape and can
  follow; doing three at once would triple the surface before one is proven.
- **No per-rule interval.** One minute for everything. A person who needs
  faster has a webhook already.
- **Unread is not assumed.** `is:unread` is a box the person ticks, not a
  default, because plenty of useful rules are about mail that arrives already
  read by a filter.
