# Jev checks across the agents Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pin the Jev version, add urgency to the team decision, and let Jev
make five more small decisions in the agents (paid move, reflection, rollback
version, reply check, release), each falling back to today's rule when Jev is
off, slow, failing or unsure.

**Architecture:** One new module, `agent_jev.py`, holds the five checks. Each
is one Jev call (a Choice or a Noul), returns a decision or None, never
raises, and records one row in a new `tasks.jev_check` table in the
background. None always means "do what the code did before". Urgency is a
third question (a Score) in the call `agent_decider` already makes, stored on
`tasks.agent_decision`. The Debug page shows both. Cut-offs come from a
calibration script run against the real Jev with labelled cases, using a rule
fixed before the run.

**Tech Stack:** FastAPI, httpx, SQLAlchemy text queries, pytest, TypeSafe
System One API (`POST /v1/systemone`).

**Production facts checked 2026-10-23 (container env):**
- `TYPESAFE_API_KEY` set, `JEV_MIN_CONFIDENCE=0.8`, `JEV_MODEL` unset
  (so `jev-latest`, which TypeSafe moves to new versions without notice).
- `AGENT_PAID_DAILY_CAP=0`: paid escalation is OFF, so the paid move check
  (Task 4) cannot fire in production until the cap is raised. Built and
  unit tested; no live run possible.

**Rules for every check:**
1. No key, a timeout (2 s), an HTTP error, an unreadable answer or an
   answer below the cut-off returns None and the old rule decides.
2. Never raises into the caller.
3. Recording is fire and forget: nobody waits on the database.
4. A daily call cap per process (`JEV_DAILY_CALLS`, default 2000, about
   $0.06 a day at measured token counts) stops checks for the rest of the
   UTC day. The team decider is not counted (it has its own path).
5. No message text is stored, only purpose, answer, number, time, tokens,
   cost (same reason as migration 057).

---

### Task 1: Real Jev answers as fixtures

Capture one real response with a Choice, a Noul and a Score from the tasks
container (the key is only there). Save to
`mcp-servers/tasks/tests/fixtures/jev_real_2026_10_23.json`. Readers are
tested against these bytes, not shapes written from the docs.

### Task 2: Pin the model (item 1)

**Files:** `agent_decider.py` (default), `docker-compose.unified.yml`
(`JEV_MODEL=${JEV_MODEL:-jev-1.13.0}`), `tests/test_agent_decider.py`.

- Failing test: `build_request(...)["model"] == "jev-1.13.0"` with no env.
- Change the default to `jev-1.13.0`. One constant `MODEL_DEFAULT` used by
  agent_jev too.

### Task 3: agent_jev core

**Files:** create `agent_jev.py`, `migrations/058_jev_check.sql`,
`migrations/rollbacks/058_jev_check.down.sql`, `tests/test_agent_jev.py`.

`ask(email, purpose, state, question) -> Answer | None` posts one question
under id `q`, reads `answers.q`, records, returns
`Answer(kind, choice, value, model, input_tokens, ms)`. Tests: no key means
no call; timeout, HTTP error and garbage give None; the daily cap stops calls;
the recorded row has no message text.

### Task 4: Paid move (item 2)

**Files:** `agent_jev.py` (`plain_question`), `agent_escalation.py`
(`decide(..., plain=None)`, `needs_plain_check`), `agent_runner.py:846`.

Choice `plain` / `work`. Asked only when the escalation is enabled, the
sticky window is open, the turn is not a follow up and `rule_reason` found
nothing, which is exactly when `is_plain_question` is consulted today.
`decide(intent, window, plain=True)` returns None, `plain=False` returns
REASON_STICKY, `plain=None` runs `is_plain_question` as today.

### Task 5: Reflection gate (item 3)

**Files:** `agent_jev.py` (`worth_remembering`), `agent_memory.py`
(`_reflect_now`).

Noul. At the top of `_reflect_now` (already detached, so nobody waits):
False (noul at or below the NO cut) skips the reflection completion; True or
None reflects as today.

### Task 6: Rollback version (item 4)

**Files:** `rollback_pick.py` (`wants_before`, `before_version`),
`agent_jev.py` (`rollback_anchor`), `routes_aiuibuilder.py` resolve route.

Only when the rules asked the person (`needs_user_choice`), the phrase says
"before" or "since" and holds no hex token. Jev picks which version (newest
12, keyed by short sha, message as the description) added the thing named;
code returns the version just older than it, through the same helper the
rules use. The route is read only and the person still confirms, and the
module invariant holds: the target is always an element of the list.

### Task 7: Reply check (item 5)

**Files:** `agent_jev.py` (`reply_answers`), `routes_agent_chat.py`
(`_run_round`).

Only on the one agent path (Jev chose one agent). After its bubble is shown,
a Noul asks whether the reply answers the message. False adds the rest of
the room, allowed to pass, to the round. The everybody passed fallback
counts against the whole queue so a chosen agent that answered is never
asked twice.

### Task 8: Release in plain words (item 6)

**Files:** `agent_jev.py` (`wants_release`), `routes_agent_turn.py` `/chat`.

Only when the exact phrase list missed, the message is at most 8 words, and
this chat has a pinned agent. Noul at or above the YES cut releases.

### Task 9: Urgency (item 7)

**Files:** `agent_decider.py` (third question `urgency`, Score with three
levels), migration `058_jev_check.sql` adds `urgency`, `urgency_confidence`
to `tasks.agent_decision`, `routes_agent_debug.py`.

A missing or unreadable urgency leaves the decision unchanged. Shown on the
Debug page only; nothing acts on it yet.

### Task 10: Debug page

New table "Jev checks": time, purpose, answer, value, used, ms, model, cost.
Urgency column on the decisions table.

### Task 11: Calibration

**Files:** `scripts/jev_checks_calibrate.py`, `tests/test_jev_checks_calibrate.py`.

Labelled cases per check, run twice in the container, cap $0.02. Rule fixed
before running:
- YES cut (release): the lowest of 0.6, 0.7, 0.8, 0.9 with zero wrong acts
  in both runs, plus one step of margin, never above 0.9.
- NO cut (reflection skip, reply fails): the highest of 0.4, 0.3, 0.2, 0.1
  with zero wrong acts in both runs, minus one step, never below 0.1.
- Choice cut (paid move, rollback): the decider's rule (0.8 unless wrong
  picks at 0.8).
- No cut with zero wrong in both runs means that check ships switched off
  (its cut set past reach), and the report says so.
Also re-run `jev_calibrate.py` to confirm the decider still has zero wrong
picks at 0.8 with the urgency question added and the model pinned.

### Task 12: Verify and deploy

Full tasks suite locally (known baseline: 3 doc_builder failures and
`test_a_cancelled_round_leaves_a_cleared_rooms_new_round_alone`). Commit,
fetch fork, rebase, push to fork. Hash-sweep the server, deploy the changed
files only, 4-layer verify, live checks with screenshots of the Debug page
in `jev-e2e-screenshots/`.
