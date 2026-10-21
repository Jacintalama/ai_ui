# Jev wait status and cut-off Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show the person a status line while Jev decides, pick the
JEV_MIN_CONFIDENCE cut-off from measured Jev answers instead of a guess, and
prove both live with screenshots.

**Architecture:** `_run_round` yields one more `working` event ("Choosing who
answers...") right before it asks Jev, only when a key is set. A calibration
script asks the real Jev about a labelled set of team messages for the two
real rosters (role names copied from production on 2026-10-21) and prints,
per cut-off, how many messages would go to one agent and how many of those
picks are wrong. It calls Jev directly, so it writes no decision rows.

**Tech Stack:** FastAPI SSE round (routes_agent_chat), agent_decider, httpx,
pytest, Playwright for the live screenshots.

**What the cut-off actually controls.** PATH_PLAN and PATH_FALLBACK do the
same thing in the round (the lead's triage runs). Only PATH_ONE_AGENT changes
behaviour, so the cut-off is a trade between coverage (messages answered by
one agent, cheaper and quieter) and wrong picks (one wrong agent answers
alone). A wrong pick is worse than a fallback, which is today's behaviour.

**Choice rule (fixed before running):** the lowest cut-off with zero wrong
one-agent picks on the set, then one step (0.05) higher as margin, never
above 0.9. If 0.8 already has wrong picks, raise it.

---

### Task 1: The wait status

**Files:**
- Modify: `mcp-servers/tasks/agent_decider.py` (add `enabled()`)
- Modify: `mcp-servers/tasks/agent_chat_render.py` (add `choosing()`)
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (`_run_round`, before `_jev_choice`)
- Test: `mcp-servers/tasks/tests/test_agent_chat_round.py`, `tests/test_agent_decider.py`

**Step 1: failing tests**
- With `TYPESAFE_API_KEY` set and a stubbed decide, the stream contains
  `Choosing who answers` before the answer.
- With no key, it does not.
- Outside the gate (named agent), it does not.
- `agent_decider.enabled()` is False with no key or a blank key, True with one.

**Step 2:** run, expect FAIL (no such text / no attribute).

**Step 3:** implement: `enabled()` returns `bool(_key())`; `render.choosing()`
draws the same `.aworking` row as `working()` but with no avatar and the words
"Choosing who answers..."; `_run_round` yields it when the gate holds, the
route is not a meeting and `agent_decider.enabled()`.

**Step 4:** run the round, decider and render tests; expect PASS.

**Step 5:** commit.

### Task 2: Calibration script

**Files:**
- Create: `mcp-servers/tasks/scripts/jev_calibrate.py`
- Test: `mcp-servers/tasks/tests/test_jev_calibrate.py`

**Step 1: failing tests** for the pure parts:
- `outcome(case, kind, kc, who, wc, cut)` returns `right`, `wrong` or
  `fallback`. `wrong` when Jev would hand a job to one agent, or hand an
  answer to an agent not in the case's accepted names.
- `table(rows, cuts)` counts right, wrong and fallback per cut-off.
- The cost watchdog stops the run once spend passes the cap.

**Step 2:** run, expect FAIL (module missing).

**Step 3:** implement. Rosters: `small` (Mia Receptionist, Ada Project
manager, Dev Developer) and `big` (Ralph's seven). About 26 labelled cases,
each with `kind` and accepted names. Calls `agent_decider.build_request` and
`agent_decider._post`; cap $0.01 (expected about $0.0006: 26 calls x about
500 tokens x $0.042 per million).

**Step 4:** run tests; expect PASS. Commit.

### Task 3: Measure and set the cut-off

**Step 1:** copy the script into the tasks container and run it there (the
key is only on the server). Save the printed table.
**Step 2:** apply the choice rule. If the number changes, change the default
in `agent_decider._min_confidence`, the compose default, and the decider
tests that pin 0.8. Commit with the table in the message.

**Result, 2026-10-21 (two full runs against jev-latest in the tasks
container, 52 calls, $0.0011 together):**

| cut  | run 1 right / wrong | run 2 right / wrong |
|------|---------------------|---------------------|
| 0.50 | 13 / 1              | 13 / 1              |
| 0.60 | 12 / 0              | 12 / 1              |
| 0.70 | 10 / 0              | 11 / 1              |
| 0.75 | 9 / 0               | 9 / 0               |
| 0.80 | 9 / 0               | 9 / 0               |
| 0.85 | 8 / 0               | 7 / 0               |
| 0.90 | 8 / 0               | 5 / 0               |

- Jev is not deterministic: one message's confidence moved by up to 0.16
  between runs (the same choice each time).
- The one wrong pick both runs: "look up current pricing for cloud hosting
  providers" went to Rex (Programmer) at 0.58 and 0.71, labelled Vera.
- Lowest cut with zero wrong in both runs is 0.75; one step of margin gives
  0.80. **The cut-off stays 0.8.** No code change.
- Who-to-ask is the strong half: every pick at 0.75 or above was right. The
  kind question is what holds messages back: clear one-agent messages such
  as "the login button does nothing" scored kind 0.04 to 0.20. Rewording
  that question is the lever for coverage, measured with this script.
- ivandermuega's two agents have no role, so both read as "team member" and
  Jev has nothing to tell them apart by.

### Task 4: Deploy and live e2e with screenshots

**Step 1:** fetch fork, check divergence, hash-sweep the server, deploy the
changed files, 4-layer verify.
**Step 2:** Playwright, signed in as the 3-agent test account, sends real
team messages from the Everyone composer. Screenshots saved to
`jev-e2e-screenshots/` in the repo root (kept out of git):
1. the "Choosing who answers..." status while Jev decides,
2. a one-agent answer (only one agent replies),
3. a fallback round (the lead's plan card or several replies),
4. the Debug page listing those decisions.
**Step 3:** delete any test job rows the e2e created; report cost.
