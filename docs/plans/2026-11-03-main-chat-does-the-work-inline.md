# The main chat does the work, and shows it (2026-11-03)

Tracked on Trello, **HS RESEARCH TEAM / To Do**, one card each. This file
holds the parts a card is too small for: what already exists, what each
piece actually needs, and the decisions that have to be made before
somebody starts building.

Asked for by Ralph on 2026-11-03, in three pieces: the app builder inline
in the main chat with progress a person can watch and a message when it is
done, video inline the same way, and automations the system suggests rather
than waits to be given.

## What already exists, so nobody rebuilds it

This is the part worth reading first. All three asks are partly built.

**Both the app builder and video are already reachable from the main chat.**
They are tools the router can pick, with notes it matches against:

    code     the person's built apps and their code: reading, changing or
             building an app
    video    the person's videos: making one, or listing the videos they
             have already made

So "build me an app" and "make me a video" already reach the right place.
Nothing needs connecting. What is missing is what happens next.

**The chat already streams progress lines.** `POST /agents/chat/stream` is
the same work as `/agents/chat` with each line sent as it happens
(`agent_progress.say`, SSE). It says who is answering and what is being
read. It does not yet say anything about a build, because a build is a
subprocess that runs far away from that code path.

**A build already says when it is done.** PR #85, merged 2026-11-03: the
page watches the build link in the reply and adds one message when the
build settles. It is not deployed, and that is a deploy problem rather than
a feature problem.

So the remaining work is narrower than the ask sounds: **live progress**,
and **the result inline rather than a link**.

## The pieces

### 1. Live progress while a build runs

A build becomes a `tasks.items` row and spawns the Claude Code CLI as a
subprocess (`routes_execution.py::_run_execution`). The steps are already
named in that file: regression baseline, agent, AutoFix, docs sweep, commit
sweep, regression guard.

What is missing is a way for those steps to reach the chat that started
them. The chat's own progress channel is per turn and the turn is long over
by the time AutoFix runs.

Decide before building: does the page poll the task row, or does the build
push to the chat? The watcher in PR #85 already polls, which argues for
extending it rather than inventing a second mechanism.

### 2. The finished app inline

A build ends with a link to `preview.html?task=<id>`. The app itself should
appear in the conversation, the way an agent's answer does.

Worth checking first: published apps are served from disk by
`main.py::serve_published_app`, and Supabase credentials are injected at
request time. Anything that embeds an app has to go through that path, not
around it.

### 3. Video inline

Same shape as the builder, and the same two halves: progress while it
renders, and the result in the conversation.

Rendering is the part with hard limits already measured: 720p only, because
1080p runs the box out of memory, and every xfade input must share timebase
and fps. Those live in the video service and nothing here changes them.

### 4. Automations the system suggests

The ask: rather than somebody inventing a rule from a blank form, the
platform proposes one from what it has seen, and accepting creates it.

The open question is where a suggestion comes from, and it has to be
answered before anything is built:

- repeated asks in chat ("summarise this card" three times this week)
- repeated manual steps the platform can already see
- both

There is a real risk worth naming: a suggestion nobody wants is noise, and
noise in the one place people read answers is expensive. Start with one
source and a visible accept, never an automatic one.

### 5. A rule that runs on a timer

Triggers today are a webhook, an email arriving, and a card changing on a
Trello list. A timer is the obvious fourth.

**But cron schedules already exist**, on their own page, running agents on a
cadence. Two places that run an agent on a schedule is a split worth closing
rather than widening.

So the decision is not "add a timer trigger". It is whether automations and
schedules become one thing. That is a bigger question than it looks and it
should be answered deliberately.

## What is blocking all of it

Auto deploy from `main` is wired and refuses to run, correctly: files on the
server differ from `main` (`agent_skills.py`, `routes_agents.py`, and a test
file that is not on the box at all). Somebody has to decide whether the
server's version or `main`'s is the real one.

Until that is settled, nothing ships by itself, including the build-finished
message in PR #85 that is already written and merged.
