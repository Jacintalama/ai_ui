# Agents hand work to each other

2026-09-28

## What this is for

> "we need the user agents in office walking, collaborating, meeting,
> talking to each other, real time, collaborate with task, building thing"

Asked what that is primarily for, the owner chose: **agents genuinely work
better together.** The point is better output, not a show. Walking, meetings
and live movement come later and must only ever report something that
actually happened.

Asked when one agent should involve another, the owner chose: **the agent
hits the edge of its own job and hands over.** The agent decides mid-task,
rather than the user convening a meeting every time.

Asked what needs permission, the owner chose: **free to hand over, but
acting still asks.** Handoffs do not interrupt. Real actions stay gated.

Asked whether a colleague should be read-only, the owner agreed, and added
that the user should be able to open it up per agent.

### Success looks like

Nora is booking a meeting, realises she needs the spec, gets it from Iris,
and comes back with one complete answer. Today she tells the owner to go ask
Iris themselves.

### Explicitly out of scope

Walking, animated meetings, and replacing the office's five-second poll with
a live stream. Those are later sub-projects and all of them depend on this
one, because until agents actually collaborate there is nothing real to
show.

## The problem this has to avoid

Agents deliberately cannot see each other. `test_agents_do_not_see_each_other`
enforces it and the code says why: feeding agents each other's replies taught
the model to invent whole exchanges between agents that never happened.

A "meeting" today routes the same question to all seven agents, each
answering in isolation. Seven monologues, not a conversation.

So the design may not simply relax that guard.

## Approach: the handoff is a tool call

A new native tool, `ask_colleague(agent, question)`, granted through
`meta.toolIds` like every other native tool.

The agent calls it mid-turn. `agent_runner`'s existing tool loop executes it
and appends the result as a `role: tool` message, and the agent carries on
writing its own answer. The handoff nests: the caller uses the answer to
finish its own sentence rather than stopping and handing the conversation
over.

### Why this shape

- **The mechanism is already proven.** `open-webui-functions/agents_tool.py`
  exposes `ask_agents`, which runs an agent's turn and returns the answer as
  a tool result. It is model-to-agent today; this is the same shape one level
  in, with a loop guard a self-calling caller now needs.
- **The invention guard is sidestepped, not fought.** The colleague receives
  a *question* and who is asking. Never a transcript. No agent is ever shown
  another agent's dialogue to continue, so the failure mode cannot arise and
  `test_agents_do_not_see_each_other` stays exactly as written.
- **The owner's guard rail falls out for free.** Asking is a read, so
  `is_write_call` is false and nothing interrupts. A colleague's own write
  calls are governed inside its own turn.
- **Collaboration and observability become one piece of work.** A handoff is
  a tool call, so recording tool calls records collaboration.

### Approaches rejected

**Router-level handoff** — the agent ends its turn with a marker like
"→ Iris: find the spec" and the round starts Iris next. No new tool, but it
depends on parsing model prose, which has bitten this project before with the
meeting regex, and it cannot nest: Nora could not use Iris's answer to finish
her own sentence.

**Shared workspace** — agents read and write a common scratchpad. Feels the
most collaborative and is precisely what the invention guard forbids: agents
reading each other's prose and continuing it.

## Permissions: a new surface, not a new setting

`agent_access.py` already owns this decision and already has the control the
owner asked for: a per-agent level on `meta.access` of `read`, `ask` or
`all`. Its docstring already anticipates this case:

> "What this protects against is an agent doing something its owner did not
> intend, including at the prompting of text the agent read somewhere else."

A colleague acting because another agent asked it to is exactly "text the
agent read somewhere else".

So add `SURFACE_COLLEAGUE` beside `SURFACE_CHANNEL` and `SURFACE_SCHEDULE`,
in the one file that owns it:

| level | mode in a handoff | why |
|---|---|---|
| `all` | `MODE_FULL` | The owner explicitly gave that agent free rein. Their agent, their connected accounts. This is the opt-in. |
| `ask` | `MODE_READ_ONLY` | Narrows rather than prompting. See below. |
| `read` or unset | `MODE_READ_ONLY` | Unchanged. |

This obeys the module's existing law that a level is a ceiling which a
surface may narrow and never widen.

### Why `ask` narrows instead of prompting

If a colleague raised `ApprovalRequired` while its caller was mid-sentence
waiting on it, the owner would get a Yes/No prompt for a conversation they
are not in, and resuming would need a two-level resume that writes the
colleague's answer back into the caller's paused turn.

Narrowing deletes that problem by construction: `ApprovalRequired` can never
be raised inside a handoff. The only agents that act are those the owner
already set to `all`, and those act without asking by the owner's own choice.

The cost is real and accepted: "Nora, ask Rex to set up the cron" becomes
Nora proposing it and the owner approving in the conversation they are
actually having, unless Rex is set to `all`.

## Safety

**Depth.** Cap of 2. A colleague's turn runs in the same asyncio task as its
caller, so a `ContextVar` carries depth without threading a parameter through
Open WebUI's native-tool plumbing.

**Cycles.** If an agent is already on the stack it cannot be asked again.
Nora → Iris → Nora is refused.

**Refusals are answers, not errors.** Over-depth, a cycle, an unknown agent,
an agent that is not the owner's, or an exhausted free pool all return that
sentence as the tool result. The caller then tells the owner plainly rather
than dying or pretending it got an answer.

**Cost and time.** At most two handoffs per turn. Agents run one at a time on
a 3.8GB box, so a colleague's turn gets a shorter timeout than a top-level
one because somebody is waiting. Escalation stays bounded by the daily paid
cap that already exists.

**Scope.** The colleague is resolved from the owner's own roster, never
trusted from the model's argument.

## Recording

A colleague's turn already creates its own `tasks.agent_run` row through
`agent_runner`. It has no link to the run that asked and no record of what it
did.

### `tasks.agent_step` (new)

One row per tool call, written where the loop already appends results.

| column | notes |
|---|---|
| `id` | |
| `run_id` | the `agent_run` this belongs to |
| `agent_id` | who ran the tool |
| `user_email` | owner scoping, as everywhere else |
| `tool` | the tool or method name |
| `target_agent_id` | set only when the tool is a handoff |
| `status` | `ok`, `failed`, `refused`, `held` |
| `started_at`, `finished_at` | |

Indexed on `run_id` and on `(user_email, started_at DESC)`.

### `tasks.agent_run` (two additions)

- `parent_run_id` — a colleague's run points at the run that asked it.
- a new `source` value `colleague`, beside `schedule` and `channel`.

That pair is what later lets the office say "Iris is helping Nora" as a fact
rather than an animation.

### No prose is stored

Not the question, not the answer. The tool name is the useful part:
`search_drive` is "searching Drive". Storing what was asked would be a
privacy cost with no payoff, and it sits badly beside the private agent
conversations shipped on 2026-09-25.

### Recording fails open

A failed insert must never cost somebody their turn, exactly like every other
post-processing step in this codebase.

## Testing

**Unit, no network**, following the module-level-seam pattern already used
here:

- `agent_access`: the new surface across all three levels, including that
  `ask` narrows to read-only and that nothing widens.
- depth refusal, cycle refusal, unknown colleague, not-your-colleague.
- the tool result for each refusal is a sentence, not an exception.
- `agent_step` rows are written with the right shape, and a failing insert
  does not raise.

**Wiring, on the server.** A real handoff between two real agents. CLAUDE.md
is explicit that `python -c "import ..."` will not catch a `NameError` inside
a function body, and that driving `_run_execution`-style wiring needs the DB
tier. The same applies here.

**The claim gets checked.** The owner chose "agents genuinely work better
together", which is a claim, so after a week `agent_step` answers it: how
often a handoff happened, how often it ended `ok`, and whether the asking run
finished cleanly. If the numbers say it is not helping, that is worth
knowing.

## Files expected to change

- `agent_access.py` — `SURFACE_COLLEAGUE` and its rules.
- `agent_runner.py` — depth ContextVar, `agent_step` writes in the tool loop.
- `agent_activity.py` — `parent_run_id`, the `colleague` source.
- `open-webui-functions/` — the new `ask_colleague` native tool.
- `migrations/052_agent_step.sql` — the table and the two `agent_run`
  columns.
- tests as above.
