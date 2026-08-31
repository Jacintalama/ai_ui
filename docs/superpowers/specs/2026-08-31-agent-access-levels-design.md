# Agent access levels, and tools in channels

Date: 2026-08-31
Status: approved, not yet implemented

## The problem

Two gaps, and they turn out to be one piece of work.

**Agents cannot use tools in channels.** `webhook-handler/gateway/pipeline.py`
catches `OWUIToolCallError` and answers "This agent tried to use one of its
tools. It can't do that here yet." So an agent that reads your mail on a
schedule cannot read it when you ask it to in Discord. Mentioning an agent
already works; the agent just cannot do anything once mentioned.

**Permission is set in the wrong place.** Today the only control is
`tasks.schedules.tool_mode`, a per-schedule `read_only` / `full` flag set on
the Cron page. It says nothing about what an agent may do anywhere else, and it
is attached to the schedule rather than to the thing being trusted.

## What we are building

A three-level access setting on each agent, and a tool loop in channels that
obeys it.

| Level | Behaviour |
|---|---|
| `read` (Read only) | Reads run. Anything that changes, sends or deletes is refused, and the agent says so. |
| `ask` (With access) | Reads run. Before a write, the agent stops and asks the owner in the channel, then continues with the answer. |
| `all` (All access) | Everything runs. |

New agents default to `ask`.

## Where the setting lives

`meta.access` on the agent's Open WebUI model row, alongside the `meta.toolIds`
that is already there. No migration: `mcp-servers/tasks/static/agents.html`
already writes `meta` on every save through `buildAgentBody`, and the browser
posts the model row to Open WebUI's own model API directly.

**This is a self-imposed guardrail, not a security boundary against the owner.**
The owner writes their own model row, so they can set their own agent to `all`
whenever they like. That is fine and intended: it is their agent acting on
their own connected accounts. What the setting protects against is the agent
doing something the owner did not intend, including at the prompting of text
the agent read from somewhere else. It must never be relied on to protect one
user from another. Per-user scoping is already done by `X-User-Email` and the
minted per-user token, and none of that changes here.

### Absent means "behave exactly as today"

Agents created before this feature have no `meta.access`. Absent is not read as
a default; it is read as "no opinion", and each caller falls back to what it
does today:

- A **schedule** with no agent-level opinion follows its own `tool_mode`, which
  is exactly current behaviour. An existing schedule set to `full` keeps
  working.
- A **channel** with no agent-level opinion is `read`. Today channels refuse
  every tool outright, so read-only is strictly an improvement and cannot
  regress anything.

Only agents created or edited after this ships carry an explicit level.

### Precedence with the per-schedule `tool_mode`

The agent's level is a **ceiling**. A schedule may narrow it and may never
widen it.

| Agent level | Schedule `tool_mode` | Effective |
|---|---|---|
| `read` | `full` | read only |
| `all` | `read_only` | read only |
| `all` | `full` | full |
| `ask` | `full` | read only (see below) |
| absent | `full` | full (today's behaviour) |
| absent | `read_only` or unset | read only (today's behaviour) |

Two controls that can each widen the other is how permission systems get holes.
One direction only.

### `ask` on a schedule is `read`

A schedule fires whether or not anybody is online, so there is nobody to ask.
An agent on `ask` running from a schedule behaves as read only, and the run
result says which action it skipped and why. The alternative is a run that
hangs at 3am waiting for an answer.

## The tool loop in channels

### A new endpoint in tasks

`POST /agents/turn`, authed with `X-Internal-Secret`, the way
`/gateway/resolve` already is.

Request:

```json
{"user_email": "...", "agent_id": "agent-scout-7d88", "messages": [...]}
```

Response, one of:

```json
{"answer": "...", "notes": ["..."]}
{"pending": {"calls": [...], "conversation": [...],
             "agent_id": "...", "user_email": "..."}}
```

The loop itself is `agent_runner._chat`, which already exists, already executes
tools correctly, and already refuses writes when told to. It stays where it is.
Copying it into `webhook-handler` would create a second copy of `is_write_tool`,
the one function that decides whether an agent may delete your data, and this
codebase has twice had access logic in two functions where fixing one left the
other open.

**The endpoint does not accept `tool_ids` from the caller.** It resolves the
agent from that user's own model listing via `agent_runner._list_agents` and
reads `meta.toolIds` and `meta.access` itself. `tool_ids` is the gate on which
native tools may execute (see `execute_tool_call`'s `allowed_native_tools`), so
letting the caller name them would move that decision outside the service that
enforces it.

### Budget

Channels get 3 tool rounds at a 60 second per-call timeout, against the
schedule path's 5 rounds at 240 seconds. Worst case drops from about 20 minutes
to about 3. Nobody watches a Discord window for 20 minutes.

`TasksClient` defaults to a 15 second timeout, so this one call passes its own
longer value.

### The gateway side

In `pipeline.py::_run`, when `_choose_agent` returned an agent, call
`_tasks.agent_turn(...)` instead of `owui.chat_completion(...)`. A message with
no agent is untouched and still goes straight to Open WebUI.

Notes ride along with the answer exactly as the schedule path does. Chat
creation, history and the transcript write all stay in the gateway; only the
source of the answer changes.

`AGENT_TOOL_CALL` stays as a fallback rather than being deleted. It costs
nothing and covers a path not thought of here.

## The approval flow

The tool loop runs inside one request and cannot sit and wait, so it ends the
turn early and resumes on the next message.

1. Reads in the batch execute normally. Writes do not.
2. `_chat` returns the conversation so far plus the pending calls, rather than
   an answer.
3. The gateway stores that under `agentpending:<platform>:<chat_id>` in the
   tasks state store with a 600 second TTL. That store already exists and
   `pipeline.py` already uses it for agent pins. The record carries the
   `user_email` it was created for, which is what step 6 re-checks: the key is
   per chat, and a group chat or a re-linked account could otherwise let one
   person approve a write another person's agent asked for.

   The stored conversation is capped the same way tool results already are.
   It holds every tool result from this turn, and the state store is a JSON
   column, so an uncapped record is a row that grows with whatever the agent
   happened to read.
4. It replies with what the agent wants to do:

```
Scout wants to run send_message (Gmail)
   to: ralph@example.com
   subject: "Q3 numbers"

Reply yes to let it, or no to skip.
```

The tool's own name and its arguments are shown, not a hand-written phrase per
tool. A phrasebook covering 300+ proxy tools would be wrong somewhere, and the
place it was wrong is exactly where somebody would approve the wrong thing.
Argument values are truncated to keep one confirmation readable.

5. The next inbound message is checked for a pending approval before routing,
   before commands and before the model.
   - **yes** (`yes`, `y`, `ok`, `okay`, `go ahead`, `do it`, `approve`,
     case-insensitive, trimmed) resumes the loop with the calls executed.
   - **no** (`no`, `n`, `stop`, `cancel`, `dont`, `don't`) resumes the loop with
     a refusal as each tool result, so the agent explains itself rather than
     going silent.
   - **anything else** drops the pending action, says so in one line, and is
     handled as an ordinary new message. Nobody gets trapped in a confirmation
     loop, which is the failure mode people hate most.

6. On resume, before anything executes: the record is deleted (so it cannot be
   replayed), the requesting user is re-checked, the agent is re-resolved, and
   its level is re-read. An agent switched to `read` between the question and
   the answer does not get its write.

7. An expired record is gone. A `yes` arriving after expiry is answered plainly
   rather than silently ignored.

Multiple writes in one round are approved as one batch, listed together. Two
questions back to back for one intent would be worse than one.

## Wording

`_chat` currently says "this schedule is set to read only" and "this scheduled
run is read only". Both are false in a Discord DM. The context noun is passed in
so the schedule path keeps its wording and a channel says something true.

## The modal

A three-way control under the Model dropdown in `agents.html`, above the
connected-apps checkboxes, with one line of honest scope underneath:

```
Access
( ) Read only
(o) With access - asks before it changes anything
( ) All access

Applies in Discord, Telegram and scheduled runs.
Web chat here always has full access.
```

## What this does not cover

**The Open WebUI web chat is not governed by this setting.** Open WebUI runs its
own tool loop internally, on the socket path used by its UI, and calls tools
directly; `agent_tools.execute_tool_call` is never reached and only ever
receives `__user__`. An agent set to Read only will still write when used from
the web chat.

This is a deliberate, accepted scope limit, and the reason the modal states it
in plain words. A control that silently fails in the first place somebody tests
it is worse than one that admits its edges. Extending enforcement to the web
chat is separate work and would need a way to intercept Open WebUI's own loop.

Also out of scope: per-tool granularity, and approval on schedules.

## Testing

The rule this project keeps relearning: every defect here has been found by
running code against reality, and every check that missed one was reasoning
about code.

**tasks**

- A write is refused under `read`, with channel wording, not schedule wording.
- A write under `ask` returns `pending` rather than executing.
- A write under `all` executes.
- The ceiling table above, every row, driven through the same function the
  schedule path uses. This is the row most likely to be wrong in a way tests
  pass over, because it is the one with two inputs.
- Absent `meta.access` reproduces today's behaviour on both paths.
- The endpoint ignores caller-supplied `tool_ids` and resolves its own.
- A resume with a changed access level does not execute.
- A resume deletes the pending record before executing, proven by a second
  resume with the same record failing.
- The run is recorded through `agent_activity` with `SOURCE_CHANNEL`.

**webhook-handler**

- An agent message goes through the tasks path; a plain message does not.
- Notes and pending prompts are delivered.
- A tasks failure still produces a readable sentence, per the rule at the top of
  `pipeline.py` that nothing on this path may fail silently.
- The pending check runs before commands, so `/help` during a pending approval
  behaves as "anything else" and does not vanish.

**On the server**

A real Discord mention, one per level. `CLAUDE.md` is explicit that wiring
inside a function body is not caught by an import or a unit test, and this
pipeline has been bitten by exactly that twice.

## Deploy

`tasks` through `scripts/deploy_orchestrator.sh`. `webhook-handler` manually,
one `scp` per changed file, because the orchestrator does not watch it and
`scp -r` silently skips files.

`agents.html` is served from the tasks image, so it ships with the rebuild.
