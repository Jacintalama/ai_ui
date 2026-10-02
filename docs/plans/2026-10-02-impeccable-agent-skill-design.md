# Impeccable as an agent skill: design

Date: 2026-10-02. Approved in chat the same day.

## Goal

An agent that has the Impeccable skill ticked on its Edit agent form (today:
Dev, `agent-dev-c82b`) builds and changes websites with the real Impeccable
design skill (https://impeccable.style, Apache 2.0, upstream v4.4.0). Not
documented: functional, and proven by a real build and a real change.

Out of scope: builds started directly from the App Builder page stay as they
are. The Open WebUI Skills page (`/workspace/skills`) is a different system
and is not used.

## What was verified before designing (2026-10-01/02)

1. Dev never writes code. `create_app` and `apply_app_change` both start an
   App Builder run (Claude Code CLI). The skill body injected into Dev's turn
   only shapes the description Dev writes.
2. Production builds run remote: `AGENT_BACKEND=remote`, user `claude-agent`
   on the same host (172.22.0.1), Claude Code 2.1.140, cwd
   `/agent/work/<slug>`. Only `apps/<slug>/` is synced there and back.
3. The build user has no skills installed. A zero-cost probe (dead API URL)
   showed that a skill symlinked into the run's own `.claude/skills/` is
   loaded, and a run without the symlink does not see it.
4. On 2.1.140, `--disallowedTools AskUserQuestion` removes the tool, and
   `--append-system-prompt` and `--max-budget-usd` are accepted.
5. Impeccable is interactive by design: its init step stops and asks the
   user, and its new-work step can start a question web page and wait. The
   engine honours `IMPECCABLE_QUESTION_DISABLED`. The build host has no
   `OPENAI_API_KEY` (so no paid image generation) and no browser.
6. The fresh-build prompt renders to 9530 characters and both executors cut
   it at `MAX_PROMPT_CHARS = 8000`, so anything appended to the prompt is
   lost. The design instructions therefore go in the system prompt.
7. Baseline, last 30 days: successful builds $0.09 to $0.38, 2 to 4.5 min,
   claude-sonnet-4-5 via OpenRouter. Run limit 600 s.

## Design

1. **Agent skill.** `mcp-servers/tasks/agent_skills/impeccable/SKILL.md`:
   Impeccable's craft floor condensed to under 4000 characters, plus how to
   brief the builder (audience, purpose, tone, what must not change).
   `allowed-tools: code`; tags chosen so "design a website" finds it.
   Credited to Impeccable under Apache 2.0.
2. **Who is calling.** `create_app` and `apply_app_change` in
   `open-webui-functions/code_tool.py` declare `__model__`, which
   `agent_tools._run_native` fills with the calling agent's id after the
   model's own arguments, so the model cannot fake it. They forward it as
   `agent_id`.
3. **Marking the job.** `routes_code` resolves the agent row for that user
   (`routes_agent_turn._resolve_agent_row`) and, when its `meta.skillIds`
   contains `impeccable`, passes `design_skill="impeccable"` to
   `_create_and_spawn_build` / `_create_and_spawn_enhance`, which store it in
   a new nullable column `tasks.items.design_skill` (migration 053). It
   survives retries and resumes because they reload the row. Any lookup
   failure leaves it unset: the build runs as today.
4. **The run.** `_stream_claude` passes the task's `design_skill` to the
   executor for the main run only (not AutoFix, verify, pre-build questions
   or plan). For such a run the executor:
   - links `/home/claude-agent/.impeccable/skills/impeccable` into
     `/agent/work/<slug>/.claude/skills/impeccable` (remote);
   - adds `--append-system-prompt <design block>`;
   - adds `AskUserQuestion` to `--disallowedTools` (merged with the model
     override list when one is set);
   - adds `--max-budget-usd` (env `IMPECCABLE_MAX_BUDGET_USD`, default 1.50);
   - sets `IMPECCABLE_QUESTION_DISABLED=1`.
   The design block: load the impeccable skill before any UI code; nobody
   can answer questions, so infer and label guesses in
   `apps/<slug>/PRODUCT.md`; code-first, no question page, live mode or
   image generation; keep the platform's stack and file layout; run
   `impeccable detect` on the app folder once and fix in one batch; a change
   to an existing app keeps its look; finish with the COMPLETED line.
5. **Host install.** `scripts/install_impeccable.sh` pins upstream commit
   `c74755d920985f7a92cef691ca970ba95f90126e` (v4.4.0) and engine 0.1.9,
   verifies the engine against its published sha256, installs the skill and
   the engine under `/home/claude-agent/.impeccable/`, and runs
   `engine-probe` as `claude-agent`. No upstream hooks or plugin are
   installed: the Stop hook would add a pass to every run.

## Error handling

Every new step fails open. An unknown agent, a missing row, a missing skill
on the host or a missing engine leaves the build running as it does today. A
run that hits the spend cap ends as an error and follows the existing retry
path (max 3 attempts).

## Testing

TDD, unit tier: the skill passes the catalogue tests and ranks first for
design queries; the tool forwards the agent id; the route marks the job only
for an agent with the skill and only for the caller's own agent; the
executor argv, env and remote command carry the flags and symlink only when
marked.

End to end on production as the test user: tick Impeccable on Dev, ask Dev
for a landing page, then for a change to it. Each run's log must show the
Skill tool loading `impeccable`, `impeccable detect` running and COMPLETED;
the pages are checked in a real browser; cost and time compared with the
baseline. Spend capped at $3 for both.

## Follow-up approved the same day (separate commit)

Raise `MAX_PROMPT_CHARS` so fresh-build, resume and Supabase prompts keep
their closing instructions, with a test that fails on today's cap.
