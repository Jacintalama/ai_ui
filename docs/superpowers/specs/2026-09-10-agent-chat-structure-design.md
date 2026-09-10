# The agent chat, properly structured

**Status:** design, awaiting review
**Date:** 2026-09-10

## Why now

The panel has been patched five times in one day: the queue, where a queued
message lands, quoted replies, an empty bubble when a turn ran out of rounds,
and the free router reporting failure as an answer. Every one was real. All
five were symptoms of the same thing, which is that the panel shows a stream
of bubbles and nothing else, so it has no way to express state.

Ralph's words: *fullest and reliable and nice UI and easy to understand*. And
separately, *fix the idle and active, it seems not accurate*.

This is a structure, not a coat of paint. Nothing below is a new capability;
it is making visible what the system already knows and currently hides.

## What is there today

```
┌ Chat with your agents ─────────────────── [Clear] ┐
│                                                    │
│                              what is in my inbox?  │
│  MI  Mia                                           │
│      Needs a reply today ...                       │
│                                                    │
│  [Ask your agents something]              [Send]   │
└────────────────────────────────────────────────────┘
```

One permanent room per person. Every agent hears every message; naming one
means only they answer. Stored in `tasks.agent_chats`, one row per person.
The store has `create_chat`, `list_chats`, `load_chat` and `delete_chat`, and
**only `create_chat` is reachable from the panel**: the other three are
written, tested and unused. There is no way to have two conversations, and
Clear is the only way to end one.

## The five things it cannot currently say

**Which conversation this is.** There is one room. A month of unrelated
questions lives in a single thread that gets summarised away as it grows, and
the summary is invisible: an agent reads it and the person cannot.

**What an agent is doing.** "Working" and nothing else. It could be waiting on
a model, running a tool, or reading somebody's mail for the fourth time. The
turn already knows; the panel is not told.

**Why something failed.** Failures arrive as prose in the thread, in the same
shape as an answer. *"That did not go through"*, *"Ada could not answer just
now"*, and until today the free router's raw complaint. A failure that looks
like an answer is a failure people re-read as an answer.

**Whether an agent is actually there.** The card says Awake, Idle, Working or
Failed. Ralph is right that it feels wrong, and the reason is that it answers
a question nobody asked. "Idle, used 11 minutes ago" is true and useless. The
useful facts are: is it doing something for me right now, and did the last
thing I asked for work.

**What it costs.** Every turn carries a brief, up to 8,000 characters of
skills, and a history budget. When a skill gets cut for space the agent is
told and the person is not.

## Approaches

**A. Structure the thread, keep one room.** Group messages into turns, give
each turn a status line, render failures as failures. No new storage. Does not
answer "which conversation is this".

**B. Structure the thread AND expose the conversations already in the store.**
As above, plus a conversation list. It needs no migration, because
`tasks.agent_chats` already holds one row per conversation and `list_chats`,
`load_chat` and `delete_chat` are already written. They are **not** tested,
though: I claimed they were while writing this and checked, and the only
tests naming those functions belong to the Fusion page's own copies. So step
5 below carries the cost of testing three database queries that have never
run in anger. **Recommended.**

**C. Rebuild the panel as a full chat client**, with search, pinning, per-agent
threads and unread counts. More than the problem, and per-agent threads
actively fight the design: the room exists so that agents hear each other.

## The design

### One turn is one block, not loose bubbles

```
┌──────────────────────────────────────────────────┐
│                        what is in my inbox?  9:41│
│                                                  │
│  ● Ada and Mia answering                    12s  │
│                                                  │
│  MI  Mia                                         │
│      Needs a reply today: None ...               │
│                                                  │
│  AD  Ada  used inbox-triage                      │
│      Nothing on your trackers today.             │
└──────────────────────────────────────────────────┘
```

A turn is your message plus everything that answered it. The status line is
part of the turn, so "who is answering and how long" has somewhere to live
that is not a bubble pretending to be a message. This is also what makes the
quoted reply unnecessary in the common case: the block already says what it
belongs to.

The data is already shaped this way. `_run_round` knows the message and every
answer to it, and messages already carry `replying_to`.

### An agent says what it is doing

The turn loop knows: it is waiting on a completion, or it is running a named
tool. Today only "working" is emitted.

```
● Mia  reading your mail          (list_unread_emails)
● Ada  looking up a skill         (find_skills)
● Ada  thinking
```

Tool names are already available at the call site. This is one more SSE event
per tool call, and it replaces the single "working" line.

### A failure looks like a failure

Not a bubble. A quiet row with the reason and, where there is one, the fix:

```
⚠ Ada could not answer.  The free models are all busy.
   Ada is set to Auto (Free).            [Change model]
```

Three failures already carry a usable reason: the router being exhausted, the
model list being stale, and running out of rounds. They are currently prose
in the thread.

### Conversations

The store already supports them. The panel gets a list, and Clear stops being
the only way to end a conversation.

```
┌ Conversations ───────────┐
│ ● Today                  │
│   Inbox and calendar     │
│   Invoice chasing        │
│ ● Yesterday              │
│   Standup                │
└──────────────────────────┘
```

New conversation, switch, rename from the first message, delete. No
migration: `tasks.agent_chats` already has one row per conversation and the
queries exist, untested and never called from anywhere.

**This changes one rule and it must be stated.** The room is currently
permanent and shared by every agent, deliberately, so agents hear each other.
Conversations do not break that: every agent still hears everything **within a
conversation**. What changes is that two unrelated subjects stop sharing a
history budget.

### Awake, Idle and Working, fixed

The current states answer the wrong question. Replace them with what somebody
actually wants to know:

| shown | means |
|---|---|
| **Working** | a run is in flight right now, with what it is doing |
| **Ready** | last run finished normally |
| **Needs you** | stopped to ask permission |
| **Failed** | last run failed, with the reason |

"Awake for ten minutes" goes. It was invented to answer "is this agent alive",
and the honest answer is that an agent is always alive and only sometimes
busy. **Ready** is true whether it ran a second ago or last week, which is why
it will not feel wrong.

The last-run time stays, as detail rather than as the state.

### What a turn cost

One quiet line at the end of a turn, on demand rather than always:

```
4 skills loaded, 2 tools used, 12s
```

The one case that must always show is a skill silently dropped for space.
`brief_for` already names them; today only the agent is told.

## What this does not change

- One round at a time. Two rounds against one conversation interleave and
  cost double.
- Every agent hears every message inside a conversation.
- Naming an agent means only they answer.
- The queue. It works and it is tested.

## Failure behaviour

| what fails | what happens |
|---|---|
| the stream drops mid-turn | the turn block stays, marked incomplete, not silently truncated |
| a conversation cannot be loaded | the panel says so and stays on the current one |
| an agent fails inside a turn | that agent's row shows the failure; the others still answer |
| the status event is lost | the turn still renders; the status line is decoration and must never be load-bearing |

## Testing

The pattern that has found every real defect this week is running the thing,
so:

- **Browser**: a turn block groups its answers; a second message mid-turn
  opens its own block in the right place; a failure renders as a failure and
  not as a bubble; switching conversations swaps the thread and not the
  agents; the status line disappears when the turn ends.
- **Unit**: the state mapping, including that Ready is Ready regardless of
  age, which is the specific thing that felt wrong.
- **Live, before it is called done**: send three messages in a row on the real
  site and read the result, because the last two panel defects were both the
  browser half being wrong while the server half was right.

## Build order

1. **The state fix.** Smallest, and the one Ralph named. No new storage.
2. **Turn blocks.** The structural change everything else sits inside.
3. **Failures as failures.** Depends on 2.
4. **What an agent is doing.** Depends on 2, and is the most visible.
5. **Conversations.** Largest, and the only step with unknowns in it: three
   store functions that have never been called. Separable, so stopping after
   4 leaves something better than today rather than something half built.

## Open question for review

The conversation list needs somewhere to live, and the panel is already a
narrow resizable column beside the agent cards. Either it becomes a third
column, which is cramped under about 1200px, or it hides behind a control at
the top of the panel.

I would put it behind a control, because the common case is one conversation
and a permanently visible list of one is wasted width. Ralph has the better
instinct for this and it is a layout decision, not a technical one.
