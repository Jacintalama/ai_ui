# Jev decider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A message to the whole agent team is first put to Jev (TypeSafe); when Jev is
sure it is one answer and sure who should give it, only that agent answers; otherwise the
round runs exactly as today (the lead's GLM triage). Every decision is recorded and shown
on a plain debug page.

**Architecture:** One new module `agent_decider.py` (request builder, answer reader, one
HTTP call with a 2 s limit, a fail-open recorder). `routes_agent_chat._run_round` calls it
inside the existing team gate, before the triage. A new table `tasks.agent_decision` holds
decisions without message text. A new route `/tasks/agents/debug` draws decisions, runs,
agent-to-agent asks and jobs as plain tables. Compose passes `TYPESAFE_API_KEY` and
`JEV_MIN_CONFIDENCE` to tasks.

**Tech Stack:** FastAPI, httpx, SQLAlchemy async text SQL, Postgres, pytest (asyncio auto).

Design: `docs/plans/2026-10-19-jev-decider-and-glm-design.md` (approved 2026-10-19).

## Facts this plan is built on (checked 2026-10-20)

1. API (docs.typesafe.ai quickstart): `POST https://api.typesafe.ai/v1/systemone`,
   `Authorization: Bearer <key>`, body `{"state": str, "model": "jev-latest",
   "questions": {id: {"type": "choice", "instructions": str, "criteria": {label: desc}}}}`.
2. Real call from the server with the saved key, 2026-10-20: HTTP 200 in 0.28 s, 436 input
   tokens. Response, verbatim:
   `{"model":"jev-1.13.0","answers":{"kind":{"type":"choice","choice":"answer","confidence":0.96,"probabilities":{"answer":0.98,"job":0.02}},"who":{"type":"choice","choice":"Dev","confidence":0.67,"probabilities":{"Ava":0.14,"Dev":0.78,"Vera":0.08}}},"usage":{"input_tokens":436,"output_tokens":68}}`
   Note `confidence` differs from the top probability; the plan uses `confidence`.
3. `tasks` has no env_file: a variable reaches the container only if compose names it.
4. Existing gate (routes_agent_chat): JOBS_ENABLED, not private, route in TEAM_ROUTES,
   2+ agents, 4+ words, no live job.

## Rules for the decision

| Jev says | Path | Effect |
|---|---|---|
| kind=answer >= MIN and who >= MIN, agent in roster | `one_agent` | only that agent speaks, may not pass, no meeting, no triage |
| kind=job >= MIN | `plan` | today's triage (GLM writes the plan) |
| anything else, timeout, HTTP error, unreadable, duplicate names | `fallback` | today's triage |
| no key | none (no call, no row) | today's triage |

MIN = `JEV_MIN_CONFIDENCE`, default 0.8.

---

### Task 1: Migration 057 `tasks.agent_decision`

**Files:**
- Create: `mcp-servers/tasks/migrations/057_agent_decision.sql`
- Create: `mcp-servers/tasks/migrations/rollbacks/057_agent_decision.down.sql`

```sql
CREATE TABLE IF NOT EXISTS tasks.agent_decision (
    id               BIGSERIAL PRIMARY KEY,
    user_email       TEXT NOT NULL,
    chat_id          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider         TEXT NOT NULL,
    model            TEXT,
    kind             TEXT,
    kind_confidence  REAL,
    agent_id         TEXT,
    agent_confidence REAL,
    path             TEXT NOT NULL,
    reason           TEXT,
    ms               INT,
    input_tokens     INT,
    cost_usd         NUMERIC(12,8)
);
CREATE INDEX IF NOT EXISTS agent_decision_user_time
    ON tasks.agent_decision (user_email, created_at DESC);
```
Rollback: `DROP TABLE IF EXISTS tasks.agent_decision;`
Additive and idempotent (db.py re-runs every migration at start). Commit.

### Task 2: `agent_decider` pure half (TDD)

**Files:** Create `mcp-servers/tasks/agent_decider.py`; Test `mcp-servers/tasks/tests/test_agent_decider.py`

Tests first (fail with ImportError), then code:
1. `build_request(message, history, agents)` returns the body: model `jev-latest`
   (env `JEV_MODEL`), questions `kind` (criteria answer/job) and `who` (criteria
   name -> role from meta.role, else meta.description, else "team member", cut to 120
   chars). State holds the team list, up to 6 earlier lines (each cut to 300 chars, the
   message itself not repeated) and the message.
2. `build_request` returns None when two agents share a name or fewer than 2 have names.
3. `read_answer(data, agents)` on the REAL response above (kind answer 0.96, who Dev 0.67)
   gives `fallback` with reason "low confidence" at MIN 0.8, and `one_agent` with Dev's id
   at MIN 0.6.
4. kind=job 0.9 -> `plan`; kind=answer 0.9 + who 0.9 -> `one_agent`; unknown name,
   missing answers, non-dict -> `fallback` "unreadable answer".
5. `cost_usd(input_tokens)` = tokens * 0.042 / 1e6.

### Task 3: `decide()` (TDD, seams `_post` and `record`)

1. No `TYPESAFE_API_KEY` -> returns None, `_post` never called, nothing recorded.
2. With key: `_post(body, key)` called once; result recorded once; returns Decision with
   `ms` set and `input_tokens` from usage.
3. `_post` raising `httpx.TimeoutException` or `asyncio.TimeoutError` -> `fallback`
   reason "timeout", recorded, no raise.
4. `_post` raising any other error -> `fallback` reason "error: <ClassName>", recorded.
5. `record` raising -> decide still returns the decision.
6. Duplicate names -> `fallback` "names not unique", `_post` not called, recorded.

`_post` uses `httpx.AsyncClient(timeout=TIMEOUT_SECONDS)` under
`asyncio.wait_for(..., TIMEOUT_SECONDS + 0.5)`, `raise_for_status`, returns `r.json()`.
`record` inserts into `tasks.agent_decision` and swallows its own errors (bookkeeping).
`recent(email, limit=50)` reads them back newest first.

### Task 4: Wire into `_run_round` (TDD in `tests/test_agent_chat_round.py`)

1. `_app` fixture also patches `agent_decider.decide` to return None (existing tests keep
   measuring today's round).
2. New tests:
   - `one_agent` naming Mia: only Mia's turn runs, may not pass, no `meeting_started`,
     triage never called, one bubble.
   - `plan`: triage called once, card as today.
   - `fallback`: triage called, everyone answers as today.
   - decide raising: triage called, round as today.
   - `one_agent` naming an id not in the roster: triage called.
   - named agent, short message, private, approval, live job: decide never called.
3. Code: compute the gate once into `team_gate`; inside, call `_jev_choice(...)`
   (wraps decide in try/except, maps agent id to roster entry); on a chosen agent set
   `speakers, may_pass, met = [chosen], False, []`; the existing triage block runs under
   `if team_gate and chosen is None:` unchanged.

### Task 5: Compose passes the key (TDD in `tests/test_agent_decider_env.py`)

Using the `_declared`/`_reaches_container` rule from `test_agent_paid_env.py`:
`TYPESAFE_API_KEY` declared with `:-` and empty default; `JEV_MIN_CONFIDENCE` default
`0.8`. Then add both lines to the tasks environment in `docker-compose.unified.yml`.

### Task 6: Debug page `/tasks/agents/debug` (TDD in `tests/test_agent_debug_page.py`)

**Files:** Create `mcp-servers/tasks/routes_agent_debug.py`; Modify `main.py` (include
router), `static/agents.html` (a "Debug" link in the roster foot).

1. 401 without identity.
2. `render_page(data, names)` (pure): four plain tables, Decisions (time, path, kind and
   confidence, agent and confidence, ms, reason, cost), Runs (time, agent, source, model,
   status, seconds, cost), Asks between agents (time, from, to, status), Jobs (created,
   status, lead, steps done/total). Agent ids shown as names. Every value HTML-escaped.
   Empty table says "None yet." No emoji, no animation.
3. Route reads the four lists for the signed-in person only (`_read(email)`, a seam),
   names via `routes_agent_jobs._names(email)`; a failed read shows "Could not read" for
   that table, never a 500.

### Task 7: DB tier for the recorder (`tests/test_agent_decider_db.py`)

`db_session_nondestructive`, people `jevtest-<hex>@example.com`; `record` then `recent`
round trip; purge own rows before and after. Run in the server container against
`aiui_test` only.

### Task 8: Verify and ship

1. Full unit suite: baseline is 3 failed (doc_builder) plus setup errors only.
2. Code review (superpowers:requesting-code-review), fix findings.
3. Commit, fetch fork, check for Ralph's commits, push to fork/main.
4. Hash-sweep server against our last deploy, deploy tasks + compose, 4-layer hash check.
5. Live e2e in the tasks container: one real team round for a real owner's roster, in
   memory (nothing saved to the chat), with the real key; assert a stored decision row with
   provider jev, model jev-*, ms, and the path taken; GLM turns run. Cost: Jev about
   $0.00002, GLM about $0.001 per agent turn; check the OpenRouter balance first.
6. Browser: open `/tasks/agents/debug` and the office on the live site, signed in, and look.
