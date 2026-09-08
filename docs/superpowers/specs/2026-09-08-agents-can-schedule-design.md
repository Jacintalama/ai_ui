# Your agents can put things on your schedule

Date: 2026-09-08
Status: awaiting review

## The problem

Your agents can tell you things and they cannot do things.

The platform runs cron jobs, schedules, video generation, App Builder,
projects, the knowledge graph, connections and Vercel deploys. Every one has a
working internal API. An agent can reach none of them. The tools installed
today are `account`, `agents`, `calendar`, `code`, `documents`,
`excel_creator`, `executive_dashboard`, `gdrive`, `gmail` and `remember`, so an
agent can read your account, read your apps, and use Google. It cannot create a
cron job, make a video, build an app or deploy anything.

Asked "do you have any work today", an agent has nothing to look at and nothing
to arrange. That is the gap.

This spec covers the first of those features, schedules, and deliberately
establishes the pattern the rest will copy. The value is in getting the pattern
right once.

## What we are building

An Open WebUI tool, `schedules`, that lets any of a person's agents see and
manage that person's own schedules by calling the API that already exists.

"Check my inbox every morning at eight and tell me what needs a reply" becomes
a schedule the agent creates, rather than a description of one it cannot make.

## The security property, and why it is structural here

`tasks.routes_schedules._resolve_caller` already decides who a caller is:

- A request carrying the matching `X-Cron-Secret` is an **operator** and may
  target any user.
- A request carrying `X-User-Email` and no secret is an **end user**, and is
  forced onto that email. `list_schedules` filters by it, and `create_schedule`
  overwrites whatever `user_email` the body claimed.

So the rule for this tool is stronger than "do not send the secret": **it does
not hold one.** Both endpoints it uses, `/schedules` and `/prefs/timezone`,
accept the end-user path, so the tool authenticates with the caller's email
alone and its valves carry no secret at all. A tool that never possesses the
operator credential cannot leak it, cannot be tricked into using it, and cannot
have it added back by a later edit without that showing up in review.

Scoping is then enforced by the endpoint rather than remembered by the tool,
which is the difference between a property and a habit.

This matters because the platform's own notes record the scheduler as unsafe to
grant by default, on the grounds that it can delete anyone's cron. That is true
of the operator path and only the operator path. A tool that cannot reach it
cannot do it.

The tool takes the email from Open WebUI's `__user__`, the same way `account`
and `gmail` do. It is never a parameter the model can set: a model that could
name the user could act as another one.

## The six methods

Each is a thin call to an endpoint that already exists.

| Method | Endpoint | Reads or writes |
|---|---|---|
| `list_my_schedules` | `GET /schedules` | read |
| `create_schedule` | `POST /schedules` | write |
| `enable_schedule` | `POST /schedules/{id}/enable` | write |
| `disable_schedule` | `POST /schedules/{id}/disable` | write |
| `delete_schedule` | `DELETE /schedules/{id}` | write |
| `trigger_schedule_now` | `POST /schedules/{id}/run-now` | write |

**The names are chosen so the safety classifier agrees with the table.**
`agent_tools.is_write_tool` splits a name into words and looks for a mutating
verb: `create`, `enable`, `disable` and `delete` are all on that list, and
`list` is a read verb, so five of the six classify correctly with no pinning.

The sixth is deliberate. `run_schedule_now` contains no known verb at all, so it
would fall to the default, which is write, and be correct by accident.
`trigger_schedule_now` contains `trigger`, which is on the write list, so it is
correct on purpose. This is the same class of problem as `my_account`, which was
classified as a write for a day because "my" and "account" are neither kind of
verb. Naming a method after a verb the classifier knows is free; relying on the
default is not.

The consequence, which is the point: an agent set to read only can tell you
what is scheduled and change nothing. Your existing access levels do the work.

## Time

`CreateScheduleIn` defaults `tz` to `Asia/Manila`. That default is wrong for
anybody who is not there, and a schedule an hour off is worse than no schedule,
because it looks like it worked.

The tool reads the person's own timezone from `GET /prefs/timezone`, which the
browser already populates and which authenticates on the same end-user path.
That endpoint always returns a zone plus a `detected` flag, deliberately, so a
caller never has to know what the platform default is.

So the tool passes the returned zone explicitly, and when `detected` is false it
says which zone it used. "I set it for eight in the morning, Asia/Manila, since
I have no timezone recorded for you" is a sentence somebody can correct. A
schedule silently an hour off is not.

Cron expressions are built by the agent, not parsed by us. The tool sends the
`cron_expr` it was given and the create response is read back to the person in
words, so "every morning at eight" is confirmed as an actual time rather than
assumed.

## Where the result goes, and one decision for you

A schedule created outside Discord or Slack has no `delivery_channel_id`, and
your cron page already labels those "No delivery (created on web)". It runs, and
the result is on the Cron Jobs page rather than pushed anywhere.

An agent-created schedule inherits that. Two options:

1. **Say so.** The agent creates the schedule and tells you, in words, that the
   result will appear on the Cron Jobs page. Honest, no new machinery.
2. **Deliver into the agent chat panel.** A scheduled run posts its result into
   the permanent room, so the thing you asked for arrives where you asked for
   it. Better, and it is the natural home now that the room exists, but it means
   the scheduler writing into `tasks.agent_chats`, which is new work.

**This spec assumes 1 and recommends 2 as the next piece.** Shipping 2 inside
this one would make the first feature carry a second feature's risk, and the
whole point of doing schedules first is to establish a pattern cheaply.

## Failure behaviour

Every method wraps its call and returns a sentence, never an exception. The
project rule is that all external calls carry try/except, and a tool that raises
inside a turn shows the person a stack trace where an answer should be.

An error never includes the exception text. An httpx error carries the request
URL, and this project has already leaked a token that way once.

A create that fails says so and does not claim a schedule exists. An agent that
reports success it did not have is the failure mode this whole day has been
about.

## Files

- Create `open-webui-functions/schedules_tool.py`, following `account_tool.py`
  for shape but NOT for auth: a `Valves` class carrying `tasks_url` and
  `timeout_seconds` only, with no `internal_secret` field, and one method per
  row of the table above.
- Create `scripts/insert_schedules_tool.py`, following
  `scripts/insert_documents_tool.py`: read the source, create or update tool id
  `schedules`, then write its valves. Open WebUI computes the function specs
  from the content on create and update, and a tool without generated specs is
  invisible to every model.
- No change to `routes_schedules.py`. The endpoints and their scoping are
  already right, and this spec deliberately adds nothing to them.

## Testing

Unit tests against a stubbed transport, in `mcp-servers/tasks/tests/`:

- The operator secret never appears in any outgoing request on any method, and
  the tool's valves have no field to put one in.
- The email sent is the one from `__user__`, and a model-supplied email is
  ignored.
- Every method's name classifies as the table says, asserted against the real
  `is_write_tool`.
- A failing call returns a sentence rather than raising, and the sentence
  carries no URL.
- The timezone read is used, and a failed read is disclosed rather than hidden.

Then, on the box: create a real schedule through an agent, see it on the Cron
Jobs page, disable it, and delete it. This feature is not verified until a
schedule made by an agent appears in the same list a person's own schedules
appear in.

## Out of scope

- Delivering results into the agent chat panel. Named above as the next piece.
- Every other platform feature: video, App Builder, projects, deploys. Each
  copies this pattern in its own spec.
- Any change to how schedules run, deliver, or are validated.
- The operator path. Nothing here touches it.
