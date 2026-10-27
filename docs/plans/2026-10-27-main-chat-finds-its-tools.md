# The main chat finds its own tools Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A message in the main chat (Auto, the default for everyone) that no
agent takes is answered by a built-in assistant that runs our own tool loop
with the tools Jev picks for that message, asks Yes/No before anything that
changes something, and can build agents from a sentence.

**Why (Lukas, standup 2026-10-27):** "control everything from the main chat",
"I don't need to be selecting the MCP service ... it just discovers them when
it needs them", "build me a team of agents and it would know how to do it".
Today Auto sends every unclaimed message to a free OpenRouter model with no
tools at all (auto_router_pipe never reads `__tools__`).

**Design (approved 2026-10-27):** option A, write tools ask first.

- The assistant is a virtual agent, `ASSISTANT_ID = "io-assistant"`, named IO,
  base `io.io` with the free pool head in `meta.llm` (agent_llm, PR #40), so
  the runner posts the real model and never a pipe. Access `ask`.
- `routes_agent_turn._resolve_agent_row` knows the id: no Open WebUI lookup,
  tools = everything the person can reach, level `ask`. So `_run_turn`,
  `_resume_turn`, pins, memory, reflection, cost rows and Jev checks all work
  unchanged for it.
- Jev picks tools: one call, one Noul per tool the person can reach
  (`agent_jev.pick_tools`), recorded as one `tool_pick` row. Picked ids go to
  the turn as an override. Jev off, failing or unsure of every tool: the full
  list, as agents get today.
- `/agents/chat` with `route_only` (the Auto pipe): when nobody is named,
  pinned, owning the subject or picked by Jev, the assistant answers. A
  failed assistant turn returns the empty list, and the pipe answers with its
  free model exactly as before.
- Yes/No in the main chat: a turn that stops to ask stores its pending call
  per chat (BotState, like the pin). The next message that is a bare yes or
  no resumes it through `_resume_turn`. This also fixes agents on Ask in the
  main chat, where "Reply yes" never resumed anything.
- `render_turns` shows a pending turn as the approval question (the IO
  pipe's wording, moved to the service), since Auto renders what the service
  sends.
- Ralph's Agent Builder tool (`open-webui-functions/agent_builder_tool.py`) is
  installed as an Open WebUI tool, so it is in the tool list and Jev can pick
  it for "build me a team of agents". `create_agent` is a write, so it asks.

**Not in scope:** other callers of `/agents/chat` (Discord, Telegram, the IO
pipe) keep `_answer_as_io`. The office never draws the assistant (it is not
in the roster).

---

### Task 1: agent_jev.pick_tools
- `ask_many(email, purpose, state, questions)` beside `ask`: one call, many
  questions, one row. `pick_tools(email, text, tools)` with a description per
  known tool id (`TOOL_NOTES`), Noul each, picked = value >= cut.
- Tests: picks above the cut only; unknown ids described by name; no key or
  failure is None; one row with the picked ids and no message text.

### Task 2: the assistant agent
- `main_assistant.py`: `ASSISTANT_ID`, `agent(llm)` builder, `SYSTEM`.
- `_resolve_agent_row` short-circuits the id. Tests: no Open WebUI listing
  read; tools are the person's; level ask; `agent_llm.on_pipe` is true.

### Task 3: tool override through the turn
- `_run_turn(..., tool_ids=None)` and `_turn_for(..., tool_ids=None)`.
- Tests: an override replaces the resolved list; None keeps it.

### Task 4: the assistant in /agents/chat
- route_only and nobody else: pick tools, run the assistant, return its turn
  (rendered without a name). Failed turn: empty list.
- Tests: answers with the picked tools; falls back to empty on failure; not
  for callers without route_only; not when an agent was picked.

### Task 5: Yes/No in the main chat
- Store pending per chat; a bare yes or no resumes; anything else drops it.
- `render_turns` renders a pending turn as the question.
- Tests: question shown; yes resumes and runs the call; no refuses; another
  person cannot answer; a non-answer clears it.

### Task 6: calibration
- `scripts/jev_checks_calibrate.py` gains labelled tool-pick cases: each a
  message, the tools it needs, and tools that are acceptable extras.
- Rule, fixed before the run: a missed tool breaks the answer, an extra one
  costs a few tokens. So the cut is the HIGHEST of 0.5 to 0.9 with zero
  missed tools in every run, then one step lower, never below 0.5. Extra
  picks are counted and reported. No cut with zero misses: the pick is off
  (cut -0.01, every tool offered, as before).

### Task 7: verify and deploy
- Changed-file tests, browser tests that load the chat pages, hash sweep,
  deploy, install the Agent Builder tool, live checks through Open WebUI's
  API: calendar, Drive, a month-old topic, "build me a team of agents" (asks
  first; answer no, so nothing is created).

**Result, 2026-10-27 (jev-1.13.0, 14 labelled messages x 16 tools, two runs,
28 calls, $0.0017; the other checks re-run unchanged):** no needed tool
missed at 0.80 or below in either run, so the cut is 0.75. At 0.75 there are
9 extra picks over 14 messages in each run, mostly "account" (cheap). A joke and a capital-city question picked nothing
(the capital picked "remember" at 0.71, under the cut).
