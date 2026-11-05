# A light lane for the App Builder, so several people can build at once

2026-11-05

## Why

Only one person can build an app at a time. A second person is refused
with a 429. Ralph hit this while testing and it reads as a bug.

It is not a bug, it is a memory guard, and the numbers say so:

| measured | value |
|---|---|
| peak memory of the `tasks` container | 873 MB |
| its hard limit | 1 GB |
| host RAM | 3805 MB |
| host swap in use, with zero builds running | 2039 of 2047 MB |
| kernel OOM kills, historically | 51 |

Two builds at once would exceed the container limit and the OOM killer
would take out `tasks`, which also serves the API, every panel and every
build's watcher. So the limit protects the platform.

The 873 MB is not the app being built. It is the tooling:

```
the tasks service itself   ~240 MB
Chromium during the smoke  ~173 MB   (measured locally, one browser, one page)
the Claude Code CLI agent  ~460 MB   (the remainder, the largest piece)
```

And almost nothing being built needs that tooling. Of 51 apps in the
repo, **50 are static sites with no database**; exactly one uses
Supabase. Most are 6 to 9 files with a single component, and many are
byte-identical in shape because they are all landing pages.

So the platform pays ~900 MB and a global lock on every build, to
produce, nearly every time, a landing page.

**The decision taken: no server upgrade.** This is solved in software.

## Intent

A new simple site is produced by **one model call**, not by spawning a
Claude Code CLI subprocess. That costs tens of megabytes instead of
~900 MB, so several of them can run at the same time on the box we
already have.

## Goals

- A new static site builds without the agent.
- Several light builds run at once; a person is not refused because
  somebody else is building.
- A light build is still published, still committed to git, still has
  version history and rollback, and still appears in the chat the same
  way as today.
- The result does not look worse than what the agent produces today.

## Non-goals

- Replacing the agent. Enhancing an existing app, anything with a
  database or login, and genuinely multi-file apps keep using it.
- A bigger server.
- Changing how apps are published or served.
- Reducing storage. Measured separately: all 51 apps are 24 MB, while
  ~10 GB of reclaimable Docker images sit on the volume. Storage is a
  different problem with a different fix.

## Anti-goals

Things that would make this a failure even if it technically works:

- The pages look visibly cheaper than today's agent output.
- A light-lane app loses git history or cannot be rolled back.
- The light lane quietly takes a job it cannot do well, for example
  something that needed a database, and the person gets a worse app
  without being told.
- The existing agent path breaks or gets slower.
- A flood of light builds exhausts memory anyway, because nothing caps
  how many run at once.

## Constraints

- `tasks` container limit is 1 GB, ~240 MB of which is the service at
  rest. The light lane's own ceiling must be set with that in mind.
- `ANTHROPIC_API_KEY` is set on the server and
  `fusion_engine.call_model` already speaks to `claude-sonnet-5`. No new
  client, no new credential.
- Apps live at `apps/<slug>/` in this monorepo and version history is
  `git log -- apps/<slug>/`. A light build must commit there or it has
  no history.
- The chat panel reads `/api/tasks/build-steps` and shows the step a
  build is on. A light build finishes in seconds, so the steps it
  reports must be honest for a fast build rather than a copy of the
  agent's six.
- Per `CLAUDE.md`: RLS and `schema.sql` are asserted by nothing today.
  The light lane must not be the thing that starts generating database
  schemas.

## The how, as decided

**Output shape.** One `index.html`, plus `README.md`. Tailwind from the
CDN, Alpine only if the page actually needs behaviour, and the
`--site-*` theme tokens declared on `:root` exactly as `app_theme`
defines them, so the appearance panel works on a light-lane app from the
first build.

**The model.** `claude-sonnet-5` through the existing
`fusion_engine.call_model`.

**Choosing the lane.** A build takes the light lane when it is a NEW
build and the request does not ask for a database, login, accounts,
saving data, or anything else that needs a backend. Anything else, and
every enhance, goes to the agent. When the light lane is declined, the
person is told which lane they got and why, so a slower build is never
a mystery.

**Concurrency.** The light lane has its own cap, separate from the
agent's one-at-a-time, set by an environment variable so it can be
tuned without a deploy. The agent lane is unchanged.

**Checking the result.** The page must be checked before it is called
done, but not by starting a browser per build. A cheap structural check
first: it parses, it has a title, it declares the theme tokens, its
local references resolve. A shared browser is the follow-up option, not
part of this.

**Committing.** Reuse `app_git.sweep_app_commit`. Nothing new.

## Left to whoever builds it

- The exact wording of the page-writing prompt.
- How the lane decision is phrased to the person.
- Which steps a light build reports, and their wording.
- The default value of the concurrency cap.
- Whether the README is written by the same call or a second one.

## Open, and deliberately not settled here

Whether a one-file page looks as good as the agent's multi-file output.
This is the main risk to the whole idea, and it is settled by generating
two or three pages and standing them next to `bean-there`, not by
argument. That comparison happens before the lane is built.
