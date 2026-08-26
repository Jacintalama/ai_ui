# Agent Tool Execution Design

**Status:** proposed, awaiting review
**Date:** 2026-08-26

## Goal

Let an AI agent actually use its tools, both on a schedule and in a channel,
with the user choosing per schedule how much an unattended agent is allowed to
do.

## The problem, established rather than assumed

Agents already carry tools. `meta.toolIds` is set, Open WebUI injects the tool
specs into the model request, and the model asks to call them. Nothing runs
them. Every call comes back `finish_reason: "tool_calls"` with empty content,
so the agent says nothing useful and the run fails.

This was tested rather than inferred. On production, against the real Triage
agent with a minted owner token:

| Request shape | Result |
|---|---|
| plain non-streaming | `finish=tool_calls`, tools requested, answer empty |
| `session_id` | `finish=tool_calls`, tools requested, answer empty |
| `chat_id` | `finish=tool_calls`, tools requested, answer empty |
| `chat_id + session_id + id` | no usable response |
| streaming | `finish=tool_calls`, tools requested, answer empty |
| streaming, no tools (control) | answers `OK` normally |

Open WebUI's tool execution loop lives in `streaming_chat_response_handler` in
`utils/middleware.py` and drives execution through its socket event emitter and
caller. `process_chat_response` dispatches on response type with no session
gate, so this is not a marker we failed to supply. The loop simply does not run
for our calls. `routers/tools.py` exposes CRUD and valves only, with no execute
endpoint, so Open WebUI cannot be asked to run a tool on our behalf either.

## The approach

Keep Open WebUI for what it already does well, and add only the missing step.

1. Ask with `tool_ids`. Open WebUI injects the specs and resolves the agent's
   model and system prompt. The model returns `tool_calls`.
2. Execute each requested call ourselves, as the schedule's owner.
3. Post the conversation back with the assistant's `tool_calls` message and one
   `role: "tool"` message per result. Repeat until the model stops asking or a
   cap is reached.

Step 3 is the load-bearing assumption and it was verified end to end on
production before this document was written: handing back a fabricated result
produced the final answer `"You currently have 4 unread emails."` with
`finish_reason: stop`. The round trip works.

### Why not reimplement the tools

The native tools are thin HTTP clients, not logic. The Gmail tool is 192 lines
whose entire job is to POST to `http://mcp-gmail:8000` with the caller's email.
The others follow the same shape. Reimplementing their method-to-endpoint
mapping in `tasks` would duplicate something that is edited elsewhere and would
drift silently the first time someone changes a tool in Open WebUI.

Instead, load the tool's own source from `public.tool` and call it the way Open
WebUI does: instantiate `Tools()`, call the named method, pass
`__user__={"email": ...}`. One source of truth.

**Security note, stated plainly.** This executes database-stored Python inside
`tasks`. That is the same code Open WebUI already executes, authored by
platform admins, but it is a new capability for `tasks`, which is also the
service that mints impersonation tokens. Anyone who can write to `public.tool`
gains code execution in `tasks`. Tool creation is admin-gated today, so this is
acceptable, but it must be a deliberate decision and not a side effect.

### Where the loop lives

In `tasks`, in one module, used by both callers. The channel gateway in
`webhook-handler` already talks to `tasks` through `TasksClient`, so it calls
this rather than growing a second copy. Two implementations of an agent loop in
two services would diverge, and the tool-execution rules below would then be
enforced in one place and not the other.

## Permission modes

Chosen by the user per schedule, because the same agent can be trusted on one
job and not another. Stored on the schedule row, defaulting to the safest.

| Mode | Behaviour |
|---|---|
| `read_only` (default) | Read tools run. A write tool is refused, the run continues, and the result says which action was declined and why. |
| `ask` | Read tools run. A write tool pauses the run and asks the owner to approve it through the schedule's delivery channel. Approved, it runs and the loop continues. Declined or timed out, it is skipped and the run says so. |
| `full` | Everything runs, including sending. |

Agents in channels keep full tool access. A person is present and reading the
reply, which is the condition the approval step exists to recreate.

### Classifying read against write

There is already an `AccessClass` in `mcp-proxy` (PUBLIC, SHARED, RESTRICTED),
but it governs which users may reach a server, not whether a call mutates
anything. It does not answer this question and is not reused.

Classification is per method, resolved at execution time:

- An explicit table for the native tools. There are seven of them and their
  methods are enumerable, so this is written out rather than guessed.
- For everything else, including the proxy's large tool surface, a verb rule:
  `list_`, `get_`, `search_`, `read_`, `fetch_`, `find_`, `describe_`, `count_`
  are reads. Everything else is a write.
- **Unknown is a write.** The default has to fail toward asking rather than
  toward acting, so a tool nobody classified cannot send mail unattended.

The mode and the decision are recorded in the run result, so a user can always
see what the agent did, what it was refused, and why.

## Delivery in phases

Phase 2 is where the genuine complexity is, so it ships separately rather than
holding up the part that works today.

**Phase 1: the loop, `read_only` and `full`.**
The tool loop, tool execution for both families, the read/write classifier, the
per-schedule setting, the Cron page control, and the run result reporting what
ran and what was refused.

**Phase 2: `ask`.**
A pending-approval row, a run that suspends and resumes rather than blocking a
worker slot, approve and decline buttons delivered to Discord and Slack, a
timeout sweep that auto-declines, and the Cron page showing a schedule waiting
on a person. This follows the existing pre-build question pattern in this
codebase (`_sweep_prebuild_question_timeouts`) rather than inventing a new one.

Until Phase 2 lands, `ask` is not offered in the UI. A mode that silently
behaves like something else is worse than a mode that is not there yet.

## Failure handling

Every failure still ends in a message the owner can read, consistent with the
existing agent runner.

- A tool that errors returns its error to the model as the tool result, so the
  agent can say what went wrong instead of the run dying.
- The loop is capped. On reaching the cap it returns what it has, and says it
  stopped early rather than pretending to be finished.
- A refused write is not an error. The run completes and reports the refusal.
- Total time stays bounded by the existing HTTP timeout budget, and the loop
  budget is spent across iterations rather than per iteration.

## Testing

- The classifier: reads pass, writes are caught, and an unknown method is
  treated as a write. This one is worth a mutation check, because a classifier
  that returns "read" for everything would pass a naive test suite.
- The loop: a tool call is executed and fed back, multiple calls in one turn all
  execute, the cap terminates, and a tool error becomes a tool result rather
  than an exception.
- Mode enforcement: the same conversation under `read_only` and under `full`
  produces a refusal in one and an execution in the other.
- Identity: the tool is executed as the schedule's owner. Following the last
  review, this gets an explicit assertion on the email used, because that is
  the security-relevant line and two mutations passed the suite last time.
- End to end on production, against a real agent, before it is called done.

## Out of scope

- Changing how tools behave in normal chat. That path already works.
- Per-tool permissions finer than read and write.
- Making Open WebUI run its own loop for API callers. Established above as not
  available to us.
