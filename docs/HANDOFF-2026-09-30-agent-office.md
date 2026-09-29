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

### 2.6 Still unverified from CLAUDE.md: RLS and `schema.sql`

`claude_executor.py` tells the build agent RLS is mandatory and asks it to
write `schema.sql`, and nothing asserts either against the live database.
CLAUDE.md is explicit that this should be gated on whether anyone is using
the feature: query `tasks.project_supabase` first. It had 0 rows as of
2026-07-23, meaning no project has ever linked a Supabase database, so the
gap currently risks no data.

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
