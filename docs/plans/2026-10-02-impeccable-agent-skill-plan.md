# Impeccable Agent Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** An agent with the Impeccable skill ticked (Dev) creates and changes
websites through App Builder runs that load the real Impeccable skill,
unattended, capped and proven on production.

**Architecture:** The agent skill lives in the catalogue like the other 67.
`create_app` and `apply_app_change` forward the calling agent's id; the tasks
route marks the job `design_skill='impeccable'` when that agent has the skill;
the main executor run of a marked job links the pinned Impeccable skill into
the run's own `.claude/skills/`, appends the unattended rules as a system
prompt and adds the safety flags. Design: `docs/plans/2026-10-02-impeccable-agent-skill-design.md`.

**Tech Stack:** FastAPI tasks service (Python 3.12, SQLAlchemy async,
pytest asyncio auto), Open WebUI tool module, Claude Code CLI 2.1.140 on the
build host, Impeccable v4.4.0 (engine 0.1.9).

All commands run from `mcp-servers/tasks/` unless they say otherwise. Local
runs expect about 130 `ERROR at setup` from DB-tier tests; that is
pre-existing.

---

### Task 1: The agent skill

**Files:**
- Create: `agent_skills/impeccable/SKILL.md`
- Test: `tests/test_agent_skill_impeccable.py`

**Step 1: Write the failing test**

```python
"""The Impeccable design skill, as an agent sees it in the catalogue."""
import os

import pytest

import agent_skills

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_FILE = os.path.join(HERE, "..", "agent_skills", "impeccable", "SKILL.md")


def test_it_is_a_valid_skill_that_needs_the_app_tool():
    skill = agent_skills.load_all(refresh=True)["impeccable"]
    assert skill["tools"] == ["code"]
    assert len(skill["body"]) <= agent_skills.MAX_SKILL_CHARS
    assert {"design", "website"} <= set(skill["tags"])


def test_it_credits_impeccable_and_its_licence():
    text = open(SKILL_FILE, encoding="utf-8").read()
    assert "impeccable.style" in text
    assert "Apache" in text


@pytest.mark.parametrize("ask", [
    "design a website",
    "redesign my landing page",
    "make my site look better",
    "polish the design of my app",
])
def test_a_design_request_finds_it_first(ask):
    agent_skills.load_all(refresh=True)
    assert agent_skills.search(ask, 5)[0]["name"] == "impeccable"
```

**Step 2:** `python -m pytest tests/test_agent_skill_impeccable.py -q`
Expected: FAIL, KeyError 'impeccable'.

**Step 3: Write `agent_skills/impeccable/SKILL.md`** (body under 4000
characters; condensed from Impeccable's craft floor).

**Step 4:** run the new test plus `tests/test_agent_skills.py`. Expected: all
pass, including the two ranking tests ("write a document", "inbox triage").

**Step 5: Commit** `agent_skills/impeccable/SKILL.md` and the test.

---

### Task 2: `design_skill.py`, the whole reach from agent to run

**Files:**
- Create: `design_skill.py`
- Test: `tests/test_design_skill.py`

Public surface:
- `IMPECCABLE = "impeccable"`
- `system_prompt(slug) -> str`: the unattended rules, slug filled in.
- `max_budget_usd() -> str`: `IMPECCABLE_MAX_BUDGET_USD`, default `"1.50"`,
  default again for blank, non-numeric or <= 0.
- `cli_args(design, slug) -> list[str]`: `[]` unless design is
  `impeccable` and slug is set; else `--append-system-prompt <rules>`,
  `--max-budget-usd <n>` and, only when `build_model.model()` is blank,
  `--disallowedTools AskUserQuestion` (the override list already has it).
- `env(design, slug) -> dict`: `{"IMPECCABLE_QUESTION_DISABLED": "1"}` or `{}`.
- `remote_prefix(design, slug) -> str`: `{ mkdir -p .claude/skills && ln -sfn
  "$HOME/.impeccable/skills/impeccable" .claude/skills/impeccable; } || true;
  export IMPECCABLE_QUESTION_DISABLED=1; ` or `""`. The `|| true` keeps
  `set -e` from failing a build over a missing skill.
- `skill_from_meta(meta) -> str | None` and `async for_agent(user_email,
  agent_id) -> str | None`: reads `public.model.meta` for that id owned by
  that email; never raises; ids not starting `agent-` never touch the DB.

**Step 1: Write the failing tests**: one per bullet above, including
"`build_model.DISALLOWED_TOOLS` contains AskUserQuestion" (guards the
override branch), the rules containing the slug, `Skill`, `impeccable`,
`NEEDS_INPUT`, `detect` and `COMPLETED`, and `for_agent` against a fake
`session` (dict meta, string meta, no row, raising execute, foreign id).

**Step 2:** run, expect ImportError.

**Step 3:** implement.

**Step 4:** run, expect PASS.

**Step 5: Commit.**

---

### Task 3: The executors carry it

**Files:**
- Modify: `local_executor.py` (run signature, env, argv with `--` before the prompt)
- Modify: `remote_executor.py` (run signature, `_build_remote_cmd(..., design=None)`)
- Modify: `agent_executor.py` (Protocol signature)
- Test: `tests/test_design_skill_executors.py`

**Step 1: Failing tests**
- Local, design on: argv has `--append-system-prompt`, `--max-budget-usd`,
  `--disallowedTools AskUserQuestion`; `args[-2] == "--"`, `args[-1] ==
  "prompt"`; env has `IMPECCABLE_QUESTION_DISABLED=1`. Reuse the
  `_local_spawn` pattern from `tests/test_build_model.py:178`.
- Local, design off: none of those flags, no env var.
- Remote, design on: `_build_remote_cmd("p", "my-app", "low", "impeccable")`
  has the `ln -sfn` prefix before `IS_SANDBOX=1 claude`, both flags, and
  `-- p` last.
- Remote, design off: identical to `_build_remote_cmd("p", "my-app", "low")`.

**Step 2:** run, expect FAIL (unexpected keyword `design`).

**Step 3:** implement:
- Local: `env.update(design_skill.env(design, slug))`; argv `...,
  *build_model.cli_args(), *design_skill.cli_args(design, slug), "--",
  prompt`.
- Remote: `prefix = build_model.remote_shell_prefix() +
  design_skill.remote_prefix(design, slug)`; design args after the model
  args, before `-- {qprompt}`.

**Step 4:** run the new tests, `tests/test_build_model.py` and
`tests/test_remote_executor.py`. Expected: PASS.

**Step 5: Commit.**

---

### Task 4: The column, the spawns and the main run

**Files:**
- Create: `migrations/053_task_design_skill.sql`,
  `migrations/rollbacks/053_task_design_skill.down.sql`
- Modify: `models.py` (TaskItem.design_skill), `routes_aiuibuilder.py`
  (`_create_and_spawn_build`, `_create_and_spawn_enhance` take and store
  `design_skill=None`), `routes_execution.py` (`_run_design(task, main_run)`
  helper; `_stream_claude(..., main_run=False)` passes `design=` to
  `executor.run` and writes `[design skill: impeccable]` into the log;
  `_run_execution`'s call at the main run passes `main_run=True`)
- Test: `tests/test_design_skill_wiring.py`

**Step 1: Failing tests:** the migration adds the nullable column
idempotently; `TaskItem.design_skill` exists; both spawn functions have a
`design_skill=None` parameter and pass it to `TaskItem(...)` (source check:
the DB tier is needed to run them); `_run_design` returns the task's value
only on the main run and None for a None task; `_stream_claude` has
`main_run=False`; `_run_execution` source passes `main_run=True` exactly once.

**Steps 2-4:** red, implement, green.

**Step 5: Commit.**

---

### Task 5: The tasks routes mark the job

**Files:**
- Modify: `routes_code.py` (`CreateIn.agent_id`, `ApplyIn.agent_id`,
  `_design_for` seam, `_spawn_build` / `_spawn_enhance` forward
  `design_skill`)
- Modify: `tests/test_routes_code.py` (fakes accept `design_skill=None`)
- Test: `tests/test_routes_code_design.py`

**Step 1: Failing tests:** create with an agent id whose lookup says
impeccable passes `design_skill="impeccable"` to `_spawn_build`; create with
no agent id passes None and never calls the lookup with anything but None;
apply forwards the same way to `_spawn_enhance`.

**Steps 2-4:** red, implement, green, plus the whole of
`tests/test_routes_code.py`.

**Step 5: Commit.**

---

### Task 6: The tool says who is calling

**Files:**
- Modify: `../../open-webui-functions/code_tool.py` (`_agent(model)`;
  `create_app` and `apply_app_change` declare `__model__: dict = {}` and
  send `agent_id`)
- Modify: `tests/test_code_tool.py` (signature expectations)
- Test: `tests/test_code_tool_agent_id.py`

**Step 1: Failing tests:** both methods declare `__model__`; with
`__model__={"id": "agent-dev-c82b"}` the posted body carries that
`agent_id`; with none it carries `agent_id=None`. Also assert, against
`agent_tools._run_native`'s real behaviour (`tests/test_agent_tools_execute.py`
pattern), that a model-supplied `__model__` argument is overwritten.

**Steps 2-4:** red, implement, green, plus every `tests/test_code_tool*.py`.

**Step 5: Commit.**

---

### Task 7: Full local suite

Run `python -m pytest tests/ -q -p no:cacheprovider`. Expected: only
`ERROR at setup` DB-tier errors and the three failures already recorded in
`docs/HANDOFF-2026-09-30-agent-office.md` section 2.9. Anything else is a
regression to fix before going on.

---

### Task 8: Install Impeccable on the build host

**Files:**
- Create: `scripts/install_impeccable.sh` (repo root)

Pins commit `c74755d920985f7a92cef691ca970ba95f90126e` and engine `0.1.9`;
downloads the source tarball and the `impeccable-linux-x64` engine, checks
the engine against its `.sha256`, installs the skill (plus upstream LICENSE,
NOTICE and an UPSTREAM_COMMIT file) to
`/home/claude-agent/.impeccable/skills/impeccable` and the engine to
`/home/claude-agent/.impeccable/bin/0.1.9/impeccable` (the launcher's
version-pinned cache), swaps directories atomically, chowns to
`claude-agent`, and runs `engine-probe` as that user.

Verify on the host as `claude-agent`:
1. `engine-probe` prints `impeccable-engine 0.1.9`.
2. In a scratch `/tmp/impeccable-check/apps/demo/` with a PRODUCT.md,
   `impeccable context --target apps/demo` from `/tmp/impeccable-check`
   loads that PRODUCT.md. If it does not, change the rules text in
   `design_skill.system_prompt` to match what the engine actually does,
   test first.
3. `impeccable detect apps/demo` runs and prints findings or none.

---

### Task 9: Deploy

1. `git fetch fork`; `main` must equal or fast-forward `fork/main`;
   `git branch -r --contains` the server's `.deploy-state` sha.
2. Hash-sweep every file to be deployed: server copy vs `cf769ec3e` vs
   container, CR-stripped. Stop on any difference not explained by this work.
3. `gh auth switch -u Jacintalama`; rebase; push `main` to `fork`.
4. One tar from `git -c core.autocrlf=false archive`, unpacked with
   `--no-same-owner`, backups first; `stat -c %u /root/proxy-server` = 0.
5. `docker compose -f docker-compose.unified.yml up -d --build tasks`
   (agent_skills is baked into the image); migration 053 runs at startup;
   check `\d tasks.items` shows `design_skill`.
6. Reinstall the `code` tool row with `scripts/insert_owui_tool.py code
   code_tool.py "<current name>" "<current description>"` (read both from the
   row first) and hash-compare `public.tool.content` with the repo file.
7. `curl -fsSL https://ai-ui.coolestdomain.win/tasks/healthz`; the catalogue
   route lists `impeccable`; stamp `.deploy-state` as JSON.

---

### Task 10: Tick Impeccable on Dev

In a real browser as the test user, Edit agent, Dev, Choose skills, tick
Impeccable, Save. Verify `meta.skillIds` on `agent-dev-c82b` contains
`impeccable` and nothing else in `meta` changed.

---

### Task 11: Prove it end to end (spend cap $3 total)

1. OpenRouter balance first; state it.
2. Zero-cost probe of the exact marked command shape on the host (dead base
   URL): init shows `impeccable` in skills and no AskUserQuestion.
3. In Dev's chat: "Build a landing page for a small bakery called Crumb and
   Co. that sells sourdough and pastries in Basel." Watch the task:
   `design_skill='impeccable'`, the log shows `[design skill: impeccable]`, a
   `Skill` tool_use with `impeccable`, a Bash call to `impeccable detect`, the
   `result` event with cost and duration, COMPLETED, AutoFix clean.
4. Open the app in a real browser at desktop and phone width; screenshot.
5. Ask Dev for a change ("make the opening hours easier to find"), approve
   it, and check the same evidence on the enhance task.
6. Stop and report if a run exceeds $1.50 or 600 s. Compare with the
   baseline ($0.09 to $0.38, 2 to 4.5 min).

---

### Task 12: Raise the prompt cap (separate commit)

**Files:**
- Modify: `claude_executor.py:15`
- Test: `tests/test_prompt_cap.py`

**Step 1: Failing test:** render a fresh-build prompt, a resume prompt and a
Supabase fresh-build prompt; after the executors' truncation
(`prompt[:MAX_PROMPT_CHARS]`), each still contains "When done successfully"
and "COMPLETED: <summary". Expected FAIL at 8000.

**Step 2:** check `git log -S "MAX_PROMPT_CHARS"` for why it was 8000 before
changing it.

**Step 3:** raise it to 32000 (the Supabase build prompt is 18401) with a
comment saying why, rerun, commit, deploy (scp + docker cp, restart), and
verify the container's value.

---

### Task 13: Clean up and record

1. Remove `/tmp/imptest*`, `/tmp/impeccable-skill.tgz` on the server.
2. Memory: a project memory for this feature (what is live, how to switch
   it off: untick the skill; `IMPECCABLE_MAX_BUDGET_USD`), and update
   MEMORY.md.
3. Report: numbered, with the measured cost and time of both runs.
