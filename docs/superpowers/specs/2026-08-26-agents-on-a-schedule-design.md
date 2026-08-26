# Agents on a schedule

Date: 2026-08-26
Status: design
Depends on: AI Agents, and agents in channels, both live

## What we are building

A schedule can name one of your agents. When it fires, that agent runs, with
its own instructions and its own tools, acting as you, and the result is
delivered where your schedules already go.

"Every weekday at 7, Triage sorts my inbox and posts it" becomes a thing you
can set up in the Cron page in about fifteen seconds.

## The decision that shapes everything

A scheduled agent is **exactly the agent you message**. Same instructions, same
tool list, same engine.

The alternative was to keep today's engine and borrow only the agent's wording.
That is a much smaller change and it was rejected: it would produce two Triages
with one name and different abilities, where the one you tested in a DM is not
the one that runs at 7am. That is the kind of difference nobody discovers until
it matters.

## What is already there, and what is not

| Needed | State |
|---|---|
| An agent is a model row with instructions and tools | Built |
| Presenting a request to Open WebUI as one user | `owui_token.mint_owui_token`, already used by pairing |
| Resolving an email to an Open WebUI user id | `routes_gateway._owui_user_id_for` |
| Sending tools with an API chat call | `tool_ids`, proved on production |
| Delivering a result to Discord or Slack | `scheduler._deliver_result` |
| The previous run's output | `schedules.last_result`, already stored |
| A column naming the agent | **Missing.** This is the new one. |

So this is one column, one branch in the scheduler, and one field in the form.

## A naming trap worth stating

`schedules.kind` is **already** `'agent'` or `'video'`, where `'agent'` means
"run the Claude Code CLI executor". A scheduled task is therefore already
called an agent, and it is not the same thing as an AI Agent.

This design does **not** add a new `kind`. It adds a nullable `agent_id`. When
it is set, the run goes through the agent path; when it is null, nothing about
today's behaviour changes. The word "kind" keeps its current meaning and no
existing row moves.

In the interface the field is called **Run as**, never "kind" and never
"agent", so the collision stays in the database where it already lives.

## How a run works

```
schedule fires
   |
   +-- agent_id is null ---> exactly what happens today (CLI executor)
   |
   +-- agent_id is set
          |
          v
   resolve the OWNER's Open WebUI user id from the schedule's email
          |
          v
   mint a short lived token for that user  (never logged, never stored)
          |
          v
   POST /api/chat/completions
        model    = the agent id
        tool_ids = the agent's own tools
        messages = [ context from the last run, the schedule's prompt ]
          |
          v
   deliver through the existing path, and store last_result as usual
```

The owner matters, not whoever is looking. A schedule belongs to one person, it
reads their mail and their files, and it runs whether or not they are online.

### Token lifetime

`mint_owui_token` defaults to 60 seconds. That is right for pairing and wrong
here: a tool-using run can take longer than a minute, and an expired token
mid-run fails in a way that looks like the agent refusing. The scheduler asks
for a longer life explicitly, and the number lives next to the HTTP timeout so
the two cannot drift apart. The gateway already carries this warning about its
own client, and it is the same trap.

## Memory between runs

The CLI executor keeps a `MEMORY.md` so a recurring task does not repeat
itself. The chat path has no such thing, and dropping that quietly would make
every daily digest say the same thing every day.

It is nearly free here, because `schedules.last_result` is already stored. The
previous result is passed as one prior turn, trimmed, with a line saying it is
what you produced last time and not to repeat it.

Trimmed, not whole: `last_result` is capped at 8000 characters, and pasting all
of it into every run would grow the prompt for no benefit and could crowd out
the actual task.

## Failure

Everything fails back to a delivered message, because a schedule nobody is
watching that silently produces nothing is worse than one that says it broke.

| When | What happens |
|---|---|
| The agent was deleted since the schedule was made | Run it the normal way, and say once in the delivered result that the agent is gone |
| The owner has no Open WebUI account | Fail the run with a readable status, as today |
| Minting fails, or the model call fails | Normal failed-run handling, same as any other failure today |
| The agent has no tools | Send no `tool_ids` at all, which is not the same as sending an empty list |

## The form

One field on the Cron page: **Run as**, a select, defaulting to the assistant
that runs schedules today. It lists the agents that person can see, by name.

Nothing else about the form changes. If somebody never touches it, their
schedules behave exactly as they do now.

## Testing

- a schedule with no agent runs the CLI path, untouched, which is the
  regression that matters most
- a schedule with an agent calls the chat path with that agent's model id
- the agent's tools are sent, and an agent with none sends no `tool_ids`
- the call is made as the schedule's OWNER, not as anyone else
- the previous result is carried into the next run, and trimmed
- an agent deleted after the schedule was made still delivers a result, and
  says why it is not the agent
- the minted token never appears in a log line

The last one is a real risk rather than a hypothetical: this project has
already logged a bot token once, because an HTTP client logged the request URL
and the token was in the path.

## Deliberately not in this spec

- **Agents in group channels.** Still a data-leak decision, still separate.
- **Choosing tools per schedule.** The agent's tools are the agent's tools. A
  schedule that quietly used a different set would be a third Triage.
- **Replacing the CLI executor.** It is better at long multi-step work and it
  keeps a real memory. Both paths stay.
