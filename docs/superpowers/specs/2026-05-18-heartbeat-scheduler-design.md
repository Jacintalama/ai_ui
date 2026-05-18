# Heartbeat Scheduler v1 — Design

**Date:** 2026-05-18
**Branch:** `feat/vm-agent-flight-mcp`
**Status:** Approved (backend + CLI only; no UI in v1)

## Context

Lukas at 2026-05-14 standup set the next-phase direction for the "open-claw" agent: **make the agent run on a schedule and remember what it already did**, in the style of open-claw / nano-claw. Headline use cases from his own words: *"watch flights Davao→Cebu, alert me on a 1-peso promo"*, *"every day at 8 p.m. watch my stocks"*, *"Friday Trello digest on WhatsApp."*

He asked for four pieces, in priority order:
1. **Cron / heartbeat scheduler** — agent VM wakes on a schedule, runs a task, sleeps. Reference: open-claw's ~3 hour interval. User-facing schedules are wall-clock.
2. **MD-file memory** — agent reads memory first, skips work already done.
3. **Persona / charisma config** — per-schedule system prompt that gives the agent a role.
4. **Secret hygiene** — secrets must never enter anything the agent reads back later (logs especially). Threat model: API key in error log → agent reads log to debug → key gets forwarded out to Anthropic / integrations.

## Goal (v1, backend + CLI only)

A schedule defined by a row in a new `tasks.schedules` table fires at the wall-clock cron expression, the orchestrator creates a `TaskItem` from it, the agent runs the existing remote-executor pipeline with the schedule's persona + memory file injected, the agent's memory writes are rsync'd back, and secrets are scrubbed at every disk-touch point.

**Out of scope for v1:** UI for creating schedules (use the CLI), natural-language-to-cron conversion, multi-tenant schedule isolation, schedule timezones beyond Asia/Manila default, retries / backoff on tick failure.

## Design

### Schema

New table `tasks.schedules`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_email` | TEXT NOT NULL | The owner — JWT lookup will tie to this |
| `name` | TEXT NOT NULL | Short label e.g. `"flights-davao-cebu"` |
| `cron_expr` | TEXT NOT NULL | 5-field cron, e.g. `"0 20 * * *"` |
| `tz` | TEXT NOT NULL DEFAULT 'Asia/Manila' | IANA tz name |
| `persona` | TEXT NOT NULL DEFAULT '' | System-prompt prefix |
| `prompt` | TEXT NOT NULL | The actual ask the agent runs each tick |
| `enabled` | BOOLEAN NOT NULL DEFAULT TRUE | Off-switch without delete |
| `last_run_at` | TIMESTAMPTZ NULL | Set after each successful tick |
| `last_run_status` | TEXT NULL | `succeeded` / `failed` / `skipped` |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Migration: add via new file `mcp-servers/tasks/migrations/001_schedules.sql`. Auto-applied on startup via existing `init_db()` (see `db.py`).

### Scheduler loop

A new file `mcp-servers/tasks/scheduler.py` defines a background coroutine spawned from `main.py`'s `lifespan`:

```python
async def schedule_tick_loop():
    while True:
        try:
            await _tick_once()
        except Exception:
            logger.exception("schedule_tick failed")
        await asyncio.sleep(60)  # one tick per minute
```

`_tick_once()`:
1. Selects all `enabled=TRUE` schedules.
2. For each, computes whether the cron expression matches the current minute in the schedule's TZ — uses the `croniter` library (already in many of our Python images; add to `mcp-servers/tasks/requirements.txt` if missing).
3. If matches AND `last_run_at` is older than 60s ago (dedupe protection — handles the case where the tick loop runs slightly late and a minute is still "current"), spawn a run.
4. A run = (a) build a `TaskItem` row using the schedule's `user_email`, `persona`+`prompt`, (b) trigger the existing execution flow (`routes_execution._run_execution`) for it.
5. After the run finishes, update `last_run_at` + `last_run_status`.

The tick loop is intentionally simple and stateless beyond the table. If the orchestrator restarts mid-tick, the next minute's tick recovers — `last_run_at` is the only state.

**Dedupe:** A schedule that already ran in the same minute is skipped. This costs one DB lookup per schedule per minute. With <100 schedules per instance, negligible.

### MD-file memory

Per-schedule memory file at `/agent/memory/<schedule-id>.md` **on the agent VM**.

**Roundtrip:**
- Before each run, `remote_executor.py` adds a pre-step: SCP `/agent/memory/<schedule-id>.md` into the run's working directory as `MEMORY.md` (create empty file if missing).
- The persona prompt is augmented with `"Before doing anything, read MEMORY.md to see what previous runs already accomplished. If your task is already done according to MEMORY.md, output 'SKIPPED: <reason>' and stop. Otherwise, do the task and append a timestamped section to MEMORY.md describing what you did, with no secrets."`
- After the run finishes, `_rsync_back` already pulls the work dir back. New step: copy the post-run `MEMORY.md` back to `/agent/memory/<schedule-id>.md` (atomically — write to `.tmp` then rename).

**Memory format:**
```markdown
# Memory for schedule: flights-davao-cebu

## 2026-05-18 20:00 Asia/Manila
Checked DAV→CEB flights for 2026-06-01 to 2026-06-15. Cheapest: PHP 2,400 on 2026-06-04 (Cebu Pacific). No 1-peso promos found. User notified via no-op (no promo to report).

## 2026-05-17 20:00 Asia/Manila
…
```

**Size cap:** 50 KB. Truncation strategy in `scheduler.py` post-run: if file > 50 KB, drop oldest `## ` sections until under cap. Keep the most recent always.

### Persona

`schedules.persona` is a plain string. The orchestrator prepends it (with a separator) to the schedule's `prompt` before dispatching the task:

```
{persona}

---

Task: {prompt}

(MEMORY.md is at the top of your working dir — read it first.)
```

Example persona:
> *"You are Lukas's personal stockbroker. Be concise, professional, mention downside risk when reporting prices. Output should fit in a single Telegram message."*

No special handling — just text concatenation.

### Secret hygiene

**Threat model** (Lukas's exact words): API key in an error log → agent later reads the log to debug → log content with the key gets forwarded back out to the internet (Anthropic, integrations, etc.).

**Mitigation: scrub secrets from anything the agent can read back.**

New module `mcp-servers/tasks/secret_scrub.py`:

```python
PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<REDACTED_ANTHROPIC>"),
    (re.compile(r"AIza[A-Za-z0-9_-]{20,}"), "<REDACTED_GOOGLE>"),
    (re.compile(r"duffel_test_[A-Za-z0-9_-]{20,}"), "<REDACTED_DUFFEL>"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<REDACTED_JWT>"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "<REDACTED_GITHUB>"),
    (re.compile(r"xoxb-[A-Za-z0-9-]{30,}"), "<REDACTED_SLACK>"),
]

def scrub(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text
```

**Where it's applied** (defense in depth — three layers):

1. **Agent-VM-side hook:** a small `/opt/io-mcp/venv/bin/io-scrub` script (added by `provision_agent_vm.sh`) runs as `claude-agent`'s post-execution step. Walks `/agent/work/<slug>/` for `*.log`, `*.txt`, `MEMORY.md` and applies `scrub`. (This module lives in `mcp-servers/io-mcp-wrappers/io_mcp_base/scrub.py` so both agent and orchestrator can share it.)
2. **Orchestrator-side rsync hook:** after `_rsync_back`, scrub `MEMORY.md` before writing it back to `/agent/memory/<id>.md`. Belt-and-braces — catches anything the agent-side missed.
3. **Stream-level scrubbing of stderr:** `remote_executor._stream` already pipes stderr→stdout. Add a `scrub(line)` call before yielding each line to the parser. Prevents secrets from landing in `TaskExecution.log` (which lives in Postgres and is queryable by future agent runs).

**Test:** Plant a fake key `sk-ant-test_abc123def456ghi789jklmno` in a file the agent reads. Run a tick. Assert: the rsync'd-back `MEMORY.md` contains `<REDACTED_ANTHROPIC>` not the key. Assert: `TaskExecution.log` contains `<REDACTED_ANTHROPIC>` not the key.

### CLI for schedule management

New file `scripts/manage_schedules.py`. Operator-friendly, talks to the orchestrator over HTTP using a service token (same `CRON_SHARED_SECRET` env var already in `routes_cron.py`).

Commands:
```
python scripts/manage_schedules.py list
python scripts/manage_schedules.py create --user me@example.com --name flights-dav-ceb --cron "0 20 * * *" --persona "You are my flight watcher..." --prompt "Check DAV->CEB flights for the next 30 days. Use io-web-search if you need news."
python scripts/manage_schedules.py disable <id>
python scripts/manage_schedules.py enable <id>
python scripts/manage_schedules.py delete <id>
python scripts/manage_schedules.py run-now <id>   # bypass cron for testing
```

New router `mcp-servers/tasks/routes_schedules.py` exposes the backing endpoints, protected by the same shared-secret header pattern as `routes_cron.py`.

### Test plan

**Unit tests** (`mcp-servers/tasks/tests/test_scheduler.py`):
1. `test_tick_matches_cron_in_tz` — schedule `0 20 * * *` Asia/Manila fires at 20:00 PHT, NOT at 12:00 UTC (regression for tz bugs).
2. `test_tick_dedupes_within_same_minute` — same schedule, two ticks in same minute → only first creates a task.
3. `test_disabled_schedule_skipped` — `enabled=FALSE` never fires.
4. `test_persona_prepended_to_prompt` — task description starts with `persona\n\n---\n\nTask:`.
5. `test_memory_truncation_keeps_newest` — 60 KB MEMORY.md → truncated to <50 KB → newest sections preserved.

**Unit tests** (`mcp-servers/tasks/tests/test_secret_scrub.py`):
1. `test_scrub_anthropic_key` — `sk-ant-abc123…` → `<REDACTED_ANTHROPIC>`.
2. `test_scrub_jwt_three_segments` — full JWT → `<REDACTED_JWT>`; partial 2-segment string unchanged.
3. `test_scrub_idempotent` — scrubbing scrubbed text is a no-op.
4. `test_scrub_does_not_redact_safe_prefixes` — `sk-ant-` alone with no key body is unchanged.

**Integration / e2e:**
1. Create a schedule via CLI for 1 minute in the future, persona = "You are a test bot. Reply with 'tick OK'.", prompt = "Say hello and write 'ran-at-<ISO timestamp>' to MEMORY.md."
2. Wait 90 s.
3. Assert `TaskItem` was created with the right `user_email`.
4. Assert `TaskExecution.status == 'completed'`.
5. Assert `MEMORY.md` on the agent VM contains the timestamp line.
6. Assert `schedules.last_run_at` ≈ now and `last_run_status='succeeded'`.
7. Plant `sk-ant-fake_test_key_payload_xyz` in the prompt itself → confirm scrubbed in the rsync'd-back log + `MEMORY.md`.

### Risks

- **Clock skew between orchestrator and agent** — if the orchestrator's wall clock is off, ticks fire at wrong times. NTP is on by default (Ubuntu's `systemd-timesyncd`), but worth a sanity check.
- **Schedule storm at startup** — if 50 schedules all match the same minute, the tick spawns 50 concurrent agent runs and the agent VM OOMs. Mitigation in v1: cap concurrent runs at 3 (semaphore in scheduler.py). v2 could queue.
- **MEMORY.md drift** — if the agent rewrites the whole file instead of appending, history is lost. Mitigation: persona instruction is explicit ("APPEND"). If observed in practice, switch to programmatic append on orchestrator side instead of trusting the model.
- **croniter not vendored** — adding a new dep. Locked to a recent version in `requirements.txt`. If install fails, scheduler can fall back to a tiny home-grown 5-field cron parser (~30 lines) — but unnecessary unless we hit problems.

### Stub for v2

- UI on `/schedules` page in `tasks` service (list / create / edit / delete).
- Natural-language schedule creation (chat → LLM → cron expr).
- Per-schedule output sink (Slack webhook, Telegram, email) so results don't only live in the task log.
- Retries with exponential backoff on tick failure.
- Heartbeat dashboard: last 7 days of tick runs per schedule, success/failure rate.

## Files changed

- `mcp-servers/tasks/migrations/001_schedules.sql` — new
- `mcp-servers/tasks/scheduler.py` — new (~200 lines)
- `mcp-servers/tasks/secret_scrub.py` — new (~30 lines)
- `mcp-servers/tasks/routes_schedules.py` — new (~150 lines)
- `mcp-servers/tasks/main.py` — register router + spawn scheduler in lifespan
- `mcp-servers/tasks/remote_executor.py` — add memory roundtrip + scrub hooks
- `mcp-servers/tasks/db.py` — load + run the new migration on init
- `mcp-servers/tasks/requirements.txt` — add `croniter`
- `mcp-servers/tasks/tests/test_scheduler.py` — new
- `mcp-servers/tasks/tests/test_secret_scrub.py` — new
- `scripts/manage_schedules.py` — new CLI
- `scripts/provision_agent_vm.sh` — install scrub script on agent VM
- `mcp-servers/io-mcp-wrappers/io_mcp_base/scrub.py` — shared module (mirror of `secret_scrub.py` so wrappers can use it too)
- `docs/agent-vm/README.md` — new section "Scheduled runs"

## Acceptance

- All 9 unit tests green.
- Live e2e: one minute-from-now schedule executes once, MEMORY.md persists across runs, persona prepended, fake API key in prompt is scrubbed in all 3 sinks (MEMORY.md, TaskExecution.log, rsync-back files).
- No red marks in test output anywhere.
