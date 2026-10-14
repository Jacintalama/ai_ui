# Agent team jobs, Part A (the engine) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or
> superpowers:subagent-driven-development in this session) to implement this
> plan task by task.

**Goal:** A message to the whole team that is really a multi-step job gets a
plan card from the lead agent; on Start, a background worker runs the steps
one at a time, posts each result in the team chat, survives the page closing
and a service restart, and the lead closes it with a final answer.

**Architecture:** Two new tables (`tasks.agent_job`, `tasks.agent_job_step`)
and five small modules in `mcp-servers/tasks/`: plan parsing (pure), triage (one
free-model call), the job store (SQL), the step brief (pure) and the worker
(an asyncio loop started in `main.py` like the scheduler). The chat round
(`routes_agent_chat._run_round`) calls triage before the speakers run. Steps
run through the existing `routes_agent_turn._run_turn`. Everything fails open,
and `AGENT_JOBS_ENABLED=false` restores today's behaviour.

**Tech stack:** FastAPI, SQLAlchemy async + asyncpg, htmx (agents page),
pytest (asyncio_mode=auto), Playwright (Python) browser tests, the local
Docker stack.

**Design:** `docs/plans/2026-10-14-agent-team-jobs-design.md` (approved).

---

## Ground rules

1. TDD every task: failing test, see it fail for the right reason, implement,
   see it pass, commit. One commit per task.
2. Commands from `mcp-servers/tasks/`:
   - unit: `python -m pytest tests/<file> -q`
   - browser: `PW_CHANNEL=chromium python -m pytest tests/browser/<file> -q -p no:cacheprovider`
   - DB tier (Tasks 1 and 9 only), against the LOCAL dev Postgres, never prod:
     ```bash
     bash scripts/dev_up.sh up            # from the repo root
     docker compose -p aiui-dev exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE aiui_test"'   # once; ignore "already exists"
     ```
     then run with `AIUI_TEST_DB=1 DATABASE_URL=postgresql://<dev user>:<dev password>@localhost:<dev pg port>/aiui_test`.
     Read the user, password and port from `.env.dev` / `docker-compose.dev.yml`
     without printing the password. If the dev Postgres port is not published
     to the host, run the DB tests inside the local tasks container instead
     (`docker exec aiui-dev-tasks-1 sh -lc 'cd /app && AIUI_TEST_DB=1 DATABASE_URL=... python -m pytest tests/test_x.py -q'`).
     Use the `db_session_nondestructive` fixture and delete only the rows the
     test created (by id). Never point this at the production database.
3. Full non-browser suite baseline (2026-10-13):
   `DATABASE_URL=postgresql://nobody@0.0.0.0:1/nobody python -m pytest tests/ -q --ignore=tests/browser`
   gave 3 failed (test_doc_builder: docx/pptx missing), 228 errors (DB setup).
   Nothing else may fail.
4. Never print secrets. No emoji or icons in code, UI or messages.
5. Match the surrounding style: explanatory comments that say why, plain
   module docstrings, `log`/`logger` as the module already uses.
6. Do not touch `static/office.html` or `static/office/**` (Part B).

---

### Task 1: The job records

**Files:**
- Create: `mcp-servers/tasks/migrations/054_agent_jobs.sql`
- Create: `mcp-servers/tasks/migrations/rollbacks/054_agent_jobs.down.sql`
  (check the naming used by existing files in `rollbacks/` and copy it)
- Create: `mcp-servers/tasks/agent_job_store.py`
- Test: `mcp-servers/tasks/tests/test_agent_job_store.py` (DB tier)

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS tasks.agent_job (
    id            TEXT PRIMARY KEY,
    user_email    TEXT NOT NULL,
    chat_id       TEXT,
    lead_agent_id TEXT NOT NULL,
    request       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'proposed'
                  CHECK (status IN ('proposed','running','needs_you','done',
                                    'failed','cancelled')),
    result        TEXT,
    seen          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agent_job_user_status
    ON tasks.agent_job (user_email, status);
-- One running (or paused) job per person.
CREATE UNIQUE INDEX IF NOT EXISTS agent_job_one_running
    ON tasks.agent_job (user_email) WHERE status IN ('running','needs_you');

CREATE TABLE IF NOT EXISTS tasks.agent_job_step (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL REFERENCES tasks.agent_job(id) ON DELETE CASCADE,
    position   INT  NOT NULL,
    agent_id   TEXT NOT NULL,
    task       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'waiting'
               CHECK (status IN ('waiting','running','done','failed','skipped')),
    attempts   INT  NOT NULL DEFAULT 0,
    result     TEXT,
    run_id     TEXT,
    UNIQUE (job_id, position)
);
```

`agent_job_store.py` (all functions async, all take a session from `db.session()`
the way `agent_activity.py` does, all fail CLOSED for writes the worker relies
on, i.e. they raise; callers decide):

- `create_proposed(user_email, chat_id, lead_agent_id, request, steps)` where
  `steps` is `[{"agent_id", "task"}]` -> job id. One transaction.
- `get(job_id) -> dict | None` with `"steps": [...]` ordered by position.
- `for_owner(job_id, user_email) -> dict | None` (same, owner-checked).
- `start(job_id, user_email) -> bool`: proposed -> running, sets started_at;
  False when not proposed, not the owner, older than 24 h, or the
  one-running index refuses (catch the unique violation, return False).
- `cancel(job_id, user_email) -> bool`: proposed/running/needs_you ->
  cancelled; remaining waiting/running steps -> skipped; finished_at.
- `set_status(job_id, status, result=None)`: done/failed set finished_at.
- `claim_next_step() -> dict | None`: the lowest-position `waiting` step of
  the oldest `running` job, flipped to `running` with attempts+1, using
  `FOR UPDATE SKIP LOCKED` so two workers can never take the same step.
  Returns the step plus its job row.
- `finish_step(step_id, status, result=None, run_id=None)`.
- `requeue_step(step_id)`: running -> waiting (retry and restart paths).
- `recover_after_restart() -> int`: every step left `running` -> `waiting`
  (its attempt stays counted); every `proposed` job older than 24 h ->
  `cancelled`. Returns how many steps were requeued.
- `unseen_count(user_email)` and `mark_seen(user_email)` for the Done badge.
- `jobs_for_chat(user_email, chat_id) -> dict[job_id, summary]`
  (status, done steps, total steps, current agent id) for drawing cards.

**Steps:**
1. Write the DB-tier tests: create -> get round trip; start only from
   proposed and only by the owner; a second start for the same person while
   one is running returns False; claim returns steps in order and never the
   same step twice (two concurrent `claim_next_step` calls via
   `asyncio.gather`); cancel skips the rest; recover requeues running steps
   and expires a 25 h old proposal (set `created_at` by UPDATE in the test).
   Clean up by deleting the jobs the test created.
2. Run against the local `aiui_test` DB: FAIL (no table / no module).
3. Write the migration, rollback and module.
4. Run: PASS. Also run the migration against a fresh `aiui_test` twice
   (idempotent: `IF NOT EXISTS`).
5. Commit: `Agent jobs: the job and step records`.

---

### Task 2: Reading a plan the lead wrote (pure)

**Files:**
- Create: `mcp-servers/tasks/agent_job_plan.py`
- Test: `mcp-servers/tasks/tests/test_agent_job_plan.py`

```python
MIN_STEPS, MAX_STEPS = 2, 6
TASK_MAX_CHARS = 300

def parse_triage(text: str, roster: list[dict]) -> list[dict] | None:
    """The lead's triage answer as steps, or None for "just answer it".

    Accepts the JSON object anywhere in the text (models wrap it in prose or
    a ```json fence). {"kind": "answer"} -> None. {"kind": "job", "steps":
    [{"agent": "<name>", "do": "<task>"}]} -> [{"agent_id", "task"}].
    Agent names are matched case-insensitively against the roster's names
    only. ANY problem returns None: unknown agent, fewer than 2 or more than
    6 steps, an empty task, bad JSON. None means the round runs as today.
    Tasks longer than TASK_MAX_CHARS are cut, not rejected.
    """

def choose_lead(roster: list[dict]) -> dict | None:
    """meta.team_lead true wins; else the first agent whose meta.role matches
    /manager|lead|coordinator|project/i; else the first agent; None if empty."""
```

Tests: a good plan; fenced JSON; prose around JSON; `answer`; unknown agent;
1 step; 7 steps; empty `do`; non-JSON; names in another case; a long task is
cut to 300; `choose_lead` for each rule including an empty roster.

Commit: `Agent jobs: read and check the lead's plan`.

---

### Task 3: Triage (one free call by the lead)

**Files:**
- Create: `mcp-servers/tasks/agent_job_triage.py`
- Test: `mcp-servers/tasks/tests/test_agent_job_triage.py`

```python
TRIAGE_MARKER = "TEAM_TRIAGE"
TRIAGE_TIMEOUT_SECONDS = 25

TRIAGE_INSTRUCTION = (
    "TEAM_TRIAGE. You lead this team: {names}. Decide how to handle the "
    "person's last message. If one answer in the chat is enough, reply "
    'exactly {{"kind": "answer"}}. If it needs several pieces of work by '
    "different team members, reply with a plan as JSON: "
    '{{"kind": "job", "steps": [{{"agent": "<a name from the team>", '
    '"do": "<what that member should do, one sentence>"}}]}} with 2 to 6 '
    "steps in the order they should happen. Reply with the JSON only.")

async def triage(email: str, lead: dict, roster: list[dict],
                 history: list[dict]) -> list[dict] | None:
    """Steps for a job, or None to run the round as today. Never raises."""
```

Implementation: the same call shape as `routes_agent_chat._summarise` (read
it): `_resolve_agent(email, lead["id"])`, then `_chat(... tool_ids=None,
tool_mode=agent_access.MODE_READ_ONLY, refusal_reason="triage does not run
tools", max_iterations=1, timeout=TRIAGE_TIMEOUT_SECONDS, intent=None)` with
`history + [{"role": "user", "content": TRIAGE_INSTRUCTION.format(names=...)}]`,
wrapped in `asyncio.wait_for(..., TRIAGE_TIMEOUT_SECONDS + 5)`. Answers equal
to `FREE_POOL_EXHAUSTED` / `ROUTER_EXHAUSTED` -> None. Any exception -> log a
warning, None. Then `agent_job_plan.parse_triage(answer, roster)`.

Import `_resolve_agent` and `_chat` the way `routes_agent_chat` does, as module
attributes the tests can monkeypatch.

Tests (monkeypatch `_resolve_agent` and `_chat`): a plan answer -> steps; an
answer object -> None; `_chat` raises -> None; `_chat` sleeps past the
timeout (patch the constant small) -> None; busy sentence -> None; the
instruction carries the marker and the roster names; tools are off
(`tool_ids=None`, read-only mode) and `intent=None`.

Commit: `Agent jobs: the lead triages a team message`.

---

### Task 4: Job and step events on the live feed

**Files:**
- Modify: `mcp-servers/tasks/agent_events.py`
- Test: `mcp-servers/tasks/tests/test_agent_events.py`

Add `job_started`, `step_started`, `step_finished`, `job_finished` to
`EVENTS`. `publish` gains `job_id: str | None`, `step: int | None`,
`of: int | None` (ints via `int()` in a try, like `chars`). Widen the test
file's `ALLOWED` with `job_id`, `step`, `of`. Tests: each new event reaches
the owner; `job_started` carries `participants` and `of`; bad ints are
dropped; no prose fields exist.

Commit: `Office feed: job and step events`.

---

### Task 5: A job step is its own run source

**Files:**
- Modify: `mcp-servers/tasks/agent_activity.py` (add `SOURCE_JOB = "job"`,
  a `job_step()` context manager and `in_job_step()`, modelled on
  `meeting_round()` / `in_meeting()`)
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`_run_turn`, the source
  expression at about line 321: job before meeting, after colleague)
- Test: `mcp-servers/tasks/tests/test_agent_activity_events.py` (or the file
  that already tests the source choice; grep `SOURCE_MEETING` in tests)

Test: a `_run_turn` inside `job_step()` starts its run with source `job`; a
colleague call inside a job step is still `colleague`. Use the existing fakes
for `start_run`.

Also add `"job"` to the Office's speaking sources? NO: Part B. Leave office
files alone.

Commit: `Agent jobs: a step's run says it is part of a job`.

---

### Task 6: The step brief (pure)

**Files:**
- Create: `mcp-servers/tasks/agent_job_brief.py`
- Test: `mcp-servers/tasks/tests/test_agent_job_brief.py`

```python
RESULT_CAP_CHARS = 2000

def step_messages(request: str, steps: list[dict], position: int,
                  names: dict[str, str]) -> list[dict]:
    """The one user message a step's agent receives.

    The person's request, the whole plan with this step marked, and the
    results of the steps before it (each cut to RESULT_CAP_CHARS). Not the
    chat transcript: feeding agents each other's replies taught the model to
    invent exchanges (see test_agents_do_not_see_each_other).
    """
```

Shape of the content (plain text):

```
The person asked the team: <request>

The plan:
1. Mia: find the three latest reports. (done)
2. Ada: compare them. <- this is your step
3. Dev: draft a summary page.

Results so far:
Step 1, Mia: <result, cut>

Do your step now and answer with its result only.
```

`final_messages(request, steps, names)`: the lead's closing brief: the
request, every step's result (cut), "Write the person a short final answer
from these results."

Tests: own step marked; later steps listed without results; results cut at
2000 with a visible "(cut)"; the final brief lists every result; names map
ids to names and fall back to the id.

Commit: `Agent jobs: what a step's agent is told`.

---

### Task 7: The plan card in the chat

**Files:**
- Modify: `mcp-servers/tasks/agent_chat_render.py` (new `job_card()`, and
  `thread()` draws stored `role == "job"` messages)
- Test: `mcp-servers/tasks/tests/test_agent_chat_render.py` (or the existing
  render test file; grep `def test_` for `thread(`)

Stored message shape (written in Task 8):
`{"role": "job", "job_id": "...", "agent_name": "<lead>", "steps":
[{"name": "Mia", "task": "..."}]}`.

`job_card(job_id, lead_name, steps, status=None)`:
- `<div class="am agent ajob" id="job-<id>">` with the lead's avatar and name;
- "Plan:" then an `<ol>` of "Name: task" items, all text escaped;
- a status line from `status` (a summary dict: `status`, `done`, `total`,
  `current_name`): proposed -> nothing; running -> "Running: step 3 of 4,
  Ada is working"; needs_you -> "Waiting for your answer above"; done ->
  "Done"; failed -> "Stopped: a step failed"; cancelled -> "Cancelled";
- buttons, plain text: proposed -> Start (`hx-post="/tasks/agents/jobs/<id>/start"`)
  and Cancel (`.../cancel`); running or needs_you -> Stop (`.../cancel`);
  others -> none. Each `hx-target="#job-<id>" hx-swap="outerHTML"`.

`thread(messages, private=False, jobs=None)`: `jobs` maps job id -> summary;
a `role == "job"` message draws `job_card(..., status=jobs.get(id))`.
Existing callers keep working (default None).

Tests: escaping of names and tasks; buttons per status; `thread()` draws the
card with its live status; an unknown job id draws the card with no buttons
(safe: nothing to act on).

Commit: `Agent jobs: the plan card in the team chat`.

---

### Task 8: The round proposes a job instead of answering

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (`_run_round`, and
  `agent_chat_thread` passes `jobs=await job_store.jobs_for_chat(...)`
  wrapped so a failure passes `None`)
- Test: `mcp-servers/tasks/tests/test_agent_chat_round.py` (its `_app` harness)

Rules, in `_run_round`, after `speakers, may_pass, why` are final and the
`private` and approval branches are done, before `met` / the speaker loop:

```python
if (JOBS_ENABLED and not private and why in TEAM_ROUTES
        and len(agents) >= 2):
    lead = agent_job_plan.choose_lead(agents)
    steps = await agent_job_triage.triage(email, lead, agents,
                                          _history_for_round(messages, s.summary))
    if steps:
        job_id = await _propose_job(email, s, lead, asked, steps)   # None on failure
        if job_id:
            ... append the stored "job" message, publish speaking_started for
            the lead (chars = len of the card text), yield the card into the
            turn, yield the empty working line, and return.
```

- `JOBS_ENABLED = os.environ.get("AGENT_JOBS_ENABLED", "true").lower() != "false"`.
- `TEAM_ROUTES = {ROUTE_ROOM, ROUTE_COLLECTIVE, ROUTE_MEETING}`.
- `_propose_job` writes via `agent_job_store.create_proposed` inside a
  try/except: any failure logs and returns None, and the round continues as
  today (fail open).
- The triage call shows "<Lead> is working..." first, so the wait is visible.

Tests (monkeypatch `agent_job_triage.triage` and the store, both on the
module the round imports):
1. Team message + steps -> one card, no speaker turns ran, stored message
   role `job` with the steps' names.
2. Triage returns None -> today's round exactly (both bubbles).
3. Triage raises -> today's round (fail open) — triage itself never raises,
   but the round must not depend on that.
4. Store raises -> today's round.
5. Private conversation, named agent, approval: triage never called.
6. `AGENT_JOBS_ENABLED=false` (reload the module with the env set) -> triage
   never called.
7. One agent only -> triage never called.

Commit: `Agent jobs: a team request becomes a plan card`.

---

### Task 9: Start, Cancel, Stop

**Files:**
- Create: `mcp-servers/tasks/routes_agent_jobs.py` (router `/tasks/agents/jobs`)
- Modify: `mcp-servers/tasks/main.py` (include the router next to
  `routes_agent_chat`'s; read how routers are included)
- Test: `mcp-servers/tasks/tests/test_routes_agent_jobs.py`

Endpoints (`user: CurrentUser = Depends(current_user)`, HTML responses like
`routes_agent_chat`):
- `POST /tasks/agents/jobs/{job_id}/start`: `job_store.start`; on True,
  publish `job_started` (lead, `of`, participants in order) and wake the
  worker (`agent_job_worker.wake()`); return the card with its new status.
  On False return the card with a note line "This plan can no longer be
  started." (expired, another job running, already started).
- `POST /tasks/agents/jobs/{job_id}/cancel`: `job_store.cancel`; tell the
  worker to cancel the running step if this job has one
  (`agent_job_worker.cancel(job_id)`); return the card.
- `GET /tasks/agents/jobs/badge`: `{"unseen": n}`; `POST .../seen` marks seen.
- Every endpoint checks ownership through `for_owner`; another person's id
  is a 404, never their plan.

Tests with a fake store and a fake worker: owner-only (404 for others); start
-> running + event + wake; start refused -> the note; cancel -> cancelled +
worker cancel; badge counts.

Commit: `Agent jobs: start, cancel and stop a plan`.

---

### Task 10: The worker

**Files:**
- Create: `mcp-servers/tasks/agent_job_worker.py`
- Modify: `mcp-servers/tasks/main.py` lifespan: start `job_loop()` next to
  `schedule_tick_loop` (same try/except shape), only when jobs are enabled,
  after calling `job_store.recover_after_restart()`
- Test: `mcp-servers/tasks/tests/test_agent_job_worker.py`

```python
MAX_PARALLEL_STEPS = 2          # across all users, 3.8 GB box
STEP_HARD_CAP_SECONDS = 300
MAX_ATTEMPTS = 2                # first try + one retry
IDLE_POLL_SECONDS = 5

async def job_loop(): ...       # claim -> run, forever; never dies on an error
def wake(): ...                 # an asyncio.Event so Start runs at once
def cancel(job_id): ...         # cancels the asyncio task running that job's step
async def run_step(step: dict) -> None:
```

`run_step` (each piece a seam the tests patch):
1. Resolve names from `_agents_for(email)`; publish `step_started`
   (agent, job_id, step=position, of=total).
2. `messages = agent_job_brief.step_messages(...)`; inside
   `agent_activity.job_step()`, `out = await asyncio.wait_for(
   routes_agent_turn._run_turn(email, agent_id, messages, brief=True),
   STEP_HARD_CAP_SECONDS)`.
3. Answer (not a failure sentence per `routes_agent_chat._failure_reason`,
   not empty): `finish_step(done, result)`, post into the team chat (below),
   publish `step_finished` (ok) and `speaking_started` for the agent.
4. `out["pending"]` (the agent wants to change something): store it in the
   room session's `pending` with a fresh ask id exactly as
   `routes_agent_chat._question_events` does, with
   `raw_pending["job_step_id"] = step id`; post the question bubble;
   `set_status(job, "needs_you")`; leave the step `running`. (Task 11
   resumes it.)
5. Failure or exception or timeout: if `attempts < MAX_ATTEMPTS`,
   `requeue_step`; else `finish_step(failed)`, skip the rest via
   `set_status(job, "failed")` + store skip, post a note from the lead:
   "<Agent> could not finish step N: <reason>. The job stopped.", publish
   `step_finished` (failed) and `job_finished` (failed).
6. After a done step, if it was the last: the lead's closing turn with
   `final_messages(...)` (same call as 2, inside `job_step()`), post it,
   `set_status(job, "done", result=answer)`, publish `job_finished` (done).
   If the closing turn fails, post a note "All steps are done; the summary
   could not be written." and still mark done.

Posting into the team chat (one helper, `post_to_room(email, message, html)`):
`s = store.get_session(email, None)`; `await _hydrate(email, s, None)`;
append the stored message (`{"role": "assistant", "agent_id", "agent_name",
"content", "job_id", "step": n, "of": m}`; the render prefixes "Step n of m"
when `step` is present: add that to `agent_bubble` callers in `thread()`
only, a small change in `agent_chat_render`), then `store.save_chat` through
the same shielded save the round uses (`_save_despite_cancel`). Never touch
`s.streaming`. The live page learns from the events (Task 12).

Tests (patch `_run_turn`, the store, `post_to_room`, `agent_events.publish`):
the happy path of 3 steps in order with the final answer; step 2 fails once
then succeeds (retry); step 2 fails twice -> job failed, step 3 skipped, note
posted; pending -> needs_you, nothing else runs for that job; timeout counts
as a failure; cancel during a step -> the task is cancelled and no result is
posted; two jobs for two people interleave but never more than 2 steps at
once (count concurrent `_run_turn` calls with a slow fake); `job_loop`
survives `claim_next_step` raising once.

Commit: `Agent jobs: the background worker`.

---

### Task 11: A held step carries on after Yes or No

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (`_apply_pending_answer`:
  after the resumed turn returns, if the popped pending had `job_step_id`,
  call `agent_job_worker.resume_after_answer(step_id, out)`)
- Modify: `mcp-servers/tasks/agent_job_worker.py` (`resume_after_answer`:
  an answer finishes the step as in run_step 3 and sets the job back to
  `running` and wakes the loop; a refusal ("No") still finishes the step with
  the agent's answer; a new pending stays `needs_you`)
- Test: `tests/test_agent_chat_approval.py` style test plus worker test

Tests: Yes -> step done, job running, worker woken; No -> step done with the
agent's words, job running; the normal (non-job) approval path is unchanged.

Commit: `Agent jobs: a step waiting on you carries on after your answer`.

---

### Task 12: The agents page follows the job live

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html` (the live-feed IIFE added
  2026-10-13, near `roundBody()`)
- Test: `mcp-servers/tasks/tests/browser/test_agents_live_roster.py`

Behaviour: on `step_finished`, `job_finished` or `job_started`, if the room
conversation is open (`#ap-agent` empty), re-fetch the thread
(`htmx.ajax("GET", "/tasks/agents/chat/thread", "#agent-thread")`, debounced
300 ms) so the step results and the card status appear without a reload.
Card buttons already work through htmx.

Tests: an SSE `step_finished` triggers one GET of the thread when the room is
open, none for a private conversation; a burst of three events triggers one
fetch.

Commit: `Agents page: a running job's results appear as they land`.

---

### Task 13: The fake model plays a job

**Files:**
- Modify: `dev/fake-llm/app.py` and `dev/fake-llm/test_app.py`

When the last user message contains `TEAM_TRIAGE`:
- if any earlier user message contains `scene:job`, answer
  `{"kind": "job", "steps": [{"agent": "Mia", "do": "Find the three latest reports."}, {"agent": "Ada", "do": "Compare them."}, {"agent": "Dev", "do": "Draft a one page summary."}]}`;
- otherwise answer `{"kind": "answer"}` at once (no FAKE_DELAY_MS), so local
  chat stays fast.

Add the scene to the docstring table. Tests for both, plus that a step brief
(which contains "this is your step") gets the normal "<Name> here" answer.

Commit: `Local dev: the fake model plays a team job`.

---

### Task 14: Prove it locally

1. `bash scripts/dev_up.sh up`; `python scripts/dev_check.py` (6 PASS);
   `python scripts/dev_e2e.py` (passes: plain team chat unchanged).
2. Write `scripts/dev_job_e2e.py` (reuse `dev_e2e` helpers): in the room send
   "scene:job prepare the weekly summary"; the card shows 3 steps; press
   Start; after step 1 lands, close the page; wait; reopen `/ai-agents`; all
   three step messages, the lead's final answer and "Done" are there.
   Second scenario: Start, then `docker compose -p aiui-dev restart tasks`
   mid-job (through `scripts/dev_up.sh` if it offers restart, else the
   project-scoped compose command with `--env-file .env.dev`), then check it
   finishes. Print plain numbered lines; exit 1 on a miss.
3. Look at it in a real browser and save screenshots to `dev/out/`.
4. One real free-model job: `bash scripts/dev_up.sh model real`, send a real
   multi-step request, record whether triage produced a valid plan and what
   it cost (free models: 0). Switch back to `fake` afterwards.
5. Run the full non-browser suite (baseline above) and every
   `tests/browser/test_agents*.py`.
6. Code review (superpowers:requesting-code-review), fix, re-run.
7. `git fetch fork`, rebase, push to `fork/main`.

### Task 15: Deploy (hash-checked, after the user says go)

Migration 054 runs at tasks boot (`db._run_migrations`). Back up the
production DB first (`pg_dump -Fc openwebui`, as in the 2026-10-13 upgrade),
hash-sweep every file to be copied against the commit the server runs, copy
with one tar piped over ssh, rebuild tasks, verify repo == host ==
container == served, `/tasks/healthz`, the two new tables exist, and a
browser check that a plain team message still answers normally. Record the
deploy in `.deploy-state` `partials`.
