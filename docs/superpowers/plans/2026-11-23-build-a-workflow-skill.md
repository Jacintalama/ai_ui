# Build-a-workflow skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A built-in skill that walks a non-technical person to an n8n workflow with plain questions.

**Architecture:** One `SKILL.md` under `mcp-servers/tasks/agent_skills/`, loaded by `agent_skills.load_all()` and offered to the main chat's skill pick. Its pick is measured live with `scripts/jev_checks_calibrate.py skills`.

**Tech Stack:** Agent Skills SKILL.md (YAML frontmatter), pytest, Jev calibration script in the tasks container.

**Spec:** `docs/superpowers/specs/2026-11-23-build-a-workflow-skill-design.md`

## Global Constraints

- Body ≤ `agent_skills.MAX_SKILL_CHARS` (4000).
- `allowed-tools: server:mcp-proxy` (the connector tools, n8n's among them).
- The pick cut stays 0.90 (`PURPOSE_SKILL_FOR`); no general case may pick the skill.

## Review Focus

1. A timed job for the assistant ("every morning summarise my inbox") must not take this skill over `morning-briefing` / `schedule-a-job`; covered by keeping the existing SKILL_CASES and adding one such case as `fine`-only.
2. "When an email arrives" must be pointed to Automations, not built as n8n; pinned by a unit test on the body.
3. No n8n connected; the body says what to tell them; pinned by a unit test.
4. Jargon to the person: the body tells the model not to say trigger/node/webhook/cron; unit test.
5. Built off and only on a yes; unit test on the body.

---

### Task 1: The skill and its unit test

**Files:** Create `mcp-servers/tasks/agent_skills/build-a-workflow/SKILL.md`; Test `mcp-servers/tasks/tests/test_build_a_workflow_skill.py`

- [ ] Write tests: loads via `agent_skills.load_all()["build-a-workflow"]`; body length ≤ MAX_SKILL_CHARS; `allowed-tools` contains `server:mcp-proxy`; body mentions `link_aiui`, `create_workflow`, "Automations", "Schedules", "switched off", "Connect"; tells the model not to say "trigger".
- [ ] Run, expect FAIL (skill missing).
- [ ] Write SKILL.md per spec steps 1–6.
- [ ] Run, expect PASS; run the existing skill tests (`tests/test_*skill*.py`).
- [ ] Commit.

### Task 2: Live pick measurement

**Files:** Modify `mcp-servers/tasks/scripts/jev_checks_calibrate.py` (SKILL_CASES)

- [ ] Add the three example jobs needing `build-a-workflow` (the CRM one may also accept `fine` none-needed? no: it still needs the skill, which then says there is no path), plus "every morning summarise my inbox" with `build-a-workflow` only in `fine`.
- [ ] Copy skill + script into the tasks container's /tmp copy, run `skills 2` there, read the table: chosen cut must be ≤ 0.90 and no general case picks the skill.
- [ ] Wrong picks → change the description, re-measure. Commit.

### Task 3: Ship

- [ ] Push, PR, CI green (unit + browser), merge (= deploy), `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`, confirm the skill loads in the live container.
