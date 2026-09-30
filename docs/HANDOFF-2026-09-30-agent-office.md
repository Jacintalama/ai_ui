# Handoff: Agent Office, 2026-09-30

Written for whoever picks this up next. Branch `feat/office-collaboration`,
pushed to GitHub. Everything described as live has been verified on
production, not assumed.

---

## 1. What is live right now

All of this is deployed to `root@46.224.193.25` and serving.

| What | Commit |
|---|---|
| Agents hand work to each other (`ask_colleague`), recorded in `tasks.agent_step` | up to `a940d08b7` |
| The office draws a real handoff: line, speech bubble, walk | `a58870d68` |
| Office layout rebuilt so every agent is visible | `63eb25a1a` |
| The office dock on `/ai-agents` sized correctly | `a9aa5ba7c` |

**Verification method.** All 18 runtime files on this branch were hashed
(CRLF normalised) against `/app/*` inside the running `tasks` container on
2026-09-30: 18 compared, 0 differing. The server also matched the previous
commit exactly before each deploy, so no teammate's work was overwritten.

**How the static pages were deployed.** `/app/static` is **baked into the
image**, and the only bind mount on `tasks` is `./:/workspace/ai_ui`. So a
static page needs both: `scp` to
`/root/proxy-server/mcp-servers/tasks/static/`, then `docker cp` into
`tasks:/app/static/`. The repo copy is what a future `--build` picks up; the
`docker cp` is what makes it live now. Do both or the change silently
reverts on the next rebuild.

---

## 2. Remaining tasks

### 2.1 Build the live office (approved, not started)

**Spec:** `docs/superpowers/specs/2026-09-29-live-agent-office-design.md`
(`709b54365`). Approved by Ralph. **Next step is the implementation plan**,
then execution.

The office polls every 5 seconds (`office.html:1464`). The spec replaces
that with an in-process event bus and one SSE endpoint, so the floor renders
within about 200ms of something happening.

Three things were checked while writing it, and each would have sunk the
design:

- `tasks` runs a **single** uvicorn process (`Dockerfile:46`, no
  `--workers`), and agent turns run in it. So an asyncio fan-out reaches
  every open page. No Redis, no second server.
- The api-gateway already forwards `text/event-stream` untouched
  (`is_event_stream` / `stream_through`, `api-gateway/main.py:315-363`).
- `EventSource` cannot set headers, but the gateway accepts the JWT from the
  `token` cookie as well as `Authorization` (`api-gateway/main.py:486-493`),
  and the office is same-origin, so `withCredentials: true` is enough.

Two decisions in the spec worth reading before changing anything:

- `tool_started` publishes an **event with no database row**. A
  start-then-finish row pair was deliberately removed in `d9b8c26b8`; that
  cost a second commit on a hot path and the cost is still real.
- `agent_handoff` needs a new `current_run()` accessor. `_RUN` is private and
  the only public reader is `parent_run()`, which answers a different
  question.

**Read the "What this does not do" section.** This removes the lag, not the
silence. On the day it was written Ralph's floor read "7 agents, none working
right now", with last runs 2 to 22 hours old. Nobody should expect a busy
office afterwards.

### 2.2 Three stale comments (small, do it while you are in there)

`routes_agent_turn.py:332`, `routes_agent_turn.py:449` and
`agent_runner.py:1024` all still say `began()` no-ops when one is already
open. It does not, and has not since `a9b096033`. The comments are in the
exact functions section 2.1 will touch.

### 2.3 One commit title leaks review process

`8587766a6` is titled "Fix ask_colleague review findings: check the row id,
deny when unscoped, classify as a read". "Fix review findings" describes how
the work was produced, not what changed. It is on an unmerged branch, so it
can still be reworded on a rebase if the branch is cleaned up before merge.

### 2.4 Branches are not merged

`feat/agent-handoff` and `feat/office-collaboration` are both unmerged.
`feat/office-collaboration` contains all of `feat/agent-handoff` plus the
office work, so **merge that one**; `feat/agent-handoff` is an ancestor and
needs no separate merge. Production already runs this code.

Five older branches are also unmerged and unrelated:
`feat/slack-video`, `feat/url-to-video`, `feat/video-default-custom`,
`feat/video-pro-brain`, `feat/video-source-wizard`. Ralph's call.

### 2.5 `.deploy-state` is stale, deliberately left alone

It reads `5db322fcd`, dated 2026-05-18. Deploys have been manual since. I did
**not** stamp it to HEAD, because the orchestrator would then skip everything
between May and now, and I only verified the files this branch changed. Stamp
it only after a sweep of everything the script watches: `mcp-servers/`,
`api-gateway/`, `Caddyfile`, `docker-compose.unified.yml`, `scripts/`.

It is JSON and the script parses `['sha']`. Writing a bare SHA breaks the
next deploy.

### 2.6 The app commit sweep is dead, and here is the actual cause

Confirmed on the box on 2026-09-30. **Every** git command in
`/root/proxy-server` fails:

```
$ git branch --show-current
fatal: detected dubious ownership in repository at '/root/proxy-server'
```

That is why `sweep_app_commit` has silently committed nothing since
2026-08-20: step 5 of `_run_execution` fails open like every other
post-processing step, so each build swallowed it. The consequence is that
`rollback_app_core` has had nothing to roll back to and the App Builder's
version list has been empty for every app built since.

The odd part, and why this needs a careful look rather than a quick
`safe.directory` line: `stat` reports the repo as `root:root` and `whoami`
is `root`, so the usual explanation does not apply. Find out why git thinks
the ownership is dubious before papering over it.

Note there are **two** places to fix, not one. The host needs it for any git
run over ssh. The sweep runs **inside the container** against
`/workspace/ai_ui`, so it needs `_run_git` to pass
`-c safe.directory=/workspace/ai_ui` (or equivalent). Fixing the host alone
will not revive the sweep.

**Before reviving it, deal with this:** the server has a complete nested
repository at `apps/create-me-a-shoe-website-fe02/assets/.git`. A sweep that
starts working will hit it and either record an embedded repo or fail. Clean
it up first.

### 2.7 Three apps exist locally but not on the server

`create-me-a-landing-page-bf8a`, `landing-page-for-aiui-bot-6c96` and
`upload-da5312a9` are committed to this branch but are not in
`/root/proxy-server/apps`. They are either deleted, renamed, or were never
built on production. Nothing serves them, so they 404 regardless of the
`tasks.published_apps` row. Worth confirming with Ralph whether to keep them
in the repo.

The other eleven were swept file by file against the server and now match it
exactly.

### 2.8 Still unverified from CLAUDE.md: RLS and `schema.sql`

`claude_executor.py` tells the build agent RLS is mandatory and asks it to
write `schema.sql`, and nothing asserts either against the live database.
CLAUDE.md is explicit that this should be gated on whether anyone is using
the feature: query `tasks.project_supabase` first. It had 0 rows as of
2026-07-23, meaning no project has ever linked a Supabase database, so the
gap currently risks no data.

### 2.9 Status update, later on 2026-09-30

- **2.2 done.** The three comments now say what `began()` does: it sets the
  run on every turn and opens the budget only when none is open.
- **2.4 done.** `feat/office-collaboration` was fast-forwarded into `main`
  (no merge commit), so `main` is what production runs.
- **2.5 done.** Every file the orchestrator watches was hash-swept against
  `main` on the host and in the tasks and webhook-handler containers, then
  `.deploy-state` was stamped. It read `a58870d68` on the box, not
  `5db322fcd`.
- **2.6 fixed, root cause found.** `stat` on `.git` says root, but git also
  checks the work tree's top directory, and `/root/proxy-server` itself was
  owned by uid 197609, the Git Bash uid a Windows-made tar carries when root
  unpacks it. Reproduced on a scratch repo, fixed with a `chown` of that one
  directory, and proven by running the real sweep in the container: the version
  list for `boxing-landing-page-a03c` went from empty to one entry. Its build
  and the other two completed builds lost while the sweep was dead (`test-crud`,
  `hello-jacint-alama-mabuhay-a714`) were given their commit. The two nested
  repos (there were two, the other at `i-want-this-portfolio-to-d065/.git`) were
  moved to `/root/sync-backup-20260930/nested-git/`. They came from the build
  agent running `git init` in the app dir and rsync copying it back, so both
  rsyncs now exclude `.git`. `_run_git` also passes `safe.directory`, so a wrong
  owner can no longer silence the sweep.
- **Still open: published apps serve dotfiles.** Before the move,
  `/apps/create-me-a-shoe-website-fe02/assets/.git/config` returned 200 to
  anyone. The repo was empty, and none is left, but `serve_published_app`
  still serves any dot path.
- **2.7 answered.** The three apps were in the server's git from 2026-07-16 and
  were later deleted from disk (17 tracked files show as ` D`). They were
  deleted, not never built. Whether the repo keeps them is Ralph's call.
- **2.8 unchanged.** `tasks.project_supabase` still has 0 rows.
- **Three tests fail on `main`, and on the code production runs** (checked in
  the container, not only locally):
  `test_agent_activity.py::test_each_cut_off_clears_the_worst_case_of_its_own_path`
  (3900s is not more than 3840s + 240s) and
  `test_agent_stale_model.py::test_the_longer_cap_still_fits_inside_the_awake_window`
  (1260s is not more than 1290s). Both follow from `6182406aa` putting the free
  pool back to four models, which made the worst case of a scheduled run and
  of a channel run longer than the windows that mark a run failed. So a
  healthy long run can be shown as failed. The third is
  `test_static_page_js.py::test_element_ids_are_unique[office.html]`, which
  reads `id="' + esc(m.id) + '"` in `office.html` as a reused id. None of the
  three were caused by today's work, and none should be "fixed" by editing
  the test.

---

## 3. Things that cost time, so you do not pay twice

**SSH to the box goes flaky in bursts.** Plain `scp` failed on three
consecutive attempts on 2026-09-30 while `ssh` on the same host worked
seconds later. What worked: pack everything into ONE gzipped tar, `scp` that
once, then unpack over a single `ssh`. Wrap every `ssh` in a retry loop of
about five. This matches an earlier incident on 2026-09-03.

**Always `sed -i 's/\r$//'` after any `scp`.** This repo checks out CRLF on
Windows, and a trailing `\r` turns a compose value into `true\r`, which reads
as false.

**Hash-sweep the server before any repo-wins deploy.** Teammates edit files
directly on the box and the server's git tree makes its own snapshot commits.
Compare CRLF-normalised, and compare against the *container*, not just the
repo path, since `/app` is baked.

**A remembered UI preference can outlive the thing it described.** The office
dock's saved height blocked the floor's own sizing suggestion
(`agents.html:3119`), so Ralph's 150px value, chosen for a floor that no
longer existed, would have made every layout fix invisible to him
permanently. Both keys are now versioned (`aiuiOfficeHeight2`,
`aiuiOfficeZoom2`). If the floor's geometry changes again, bump them again.

**A test fixture that serves one page for every path will lie to you.** It
cost two separate false alarms in one session. In `test_office_page.py` it
served `agents.html` for the office iframe and produced infinite nesting. In
`test_agents_tools_live.py` it served `agents.html` for `/tasks/office`, so
the page bootstrapped twice inside its own iframe and
`test_the_page_seeds_once_on_load` failed, which looked exactly like the
duplicate-agents incident of 2026-08-27. It was the fixture both times. Fixed
in this branch.

---

## 4. Test status

```
mcp-servers/tasks$ python -m pytest tests/browser/ -q
```

All browser tests pass on this branch as of 2026-09-30.

Expect about 130 errors if you run the full `tests/` suite locally: anything
using the `db_session` fixture fails at setup because there is no local
Postgres. That is pre-existing. Confirm by checking the failures say `ERROR at
setup`. To run that tier for real:

```
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_x.py -q'"
```

**Before touching `db_session`, read `tests/conftest.py`.** `AIUI_TEST_DB=1`
once wiped 9 production projects and all chat history. Destructive DB tests
require BOTH `AIUI_TEST_DB=1` and a `DATABASE_URL` containing `test`.

---

## 5. Where the office code lives

- `mcp-servers/tasks/static/office.html`: the floor. `layoutFloor` sizes the
  canvas from the rooms, `bestLayout` picks the shape that fits the dock,
  `fitBox` measures the space available, `whoHtml` draws one agent.
- `mcp-servers/tasks/static/agents.html`: the page the office is docked in.
  The dock, grip and height logic start near line 2939.
- `mcp-servers/tasks/agent_activity.py`: what the floor reads.
- `mcp-servers/tasks/agent_handoff.py`: depth, cycles and per-turn budget.
- `mcp-servers/tasks/tests/browser/test_office_page.py`: the floor.
- `mcp-servers/tasks/tests/browser/test_office_inline.py`: the floor **in
  the dock**. Several defects are only measurable here.

The layout rule worth keeping: an agent is one slot in normal flow, a room is
however big its slots make it, and the canvas is however big its rooms make
it. Nothing is positioned by hand, which is what stops an agent being drawn
outside its own room.
