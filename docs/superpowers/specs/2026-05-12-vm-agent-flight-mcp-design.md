# Spec — VM-hosted Agent + Flight MCP for the IO App Builder

**Date:** 2026-05-12
**Status:** Draft — awaiting spec review
**Related branches:** `feat/functional-templates` (merged) → `feat/vm-agent-flight-mcp` (this spec)
**Author:** brainstormed with Lukas via the superpowers/brainstorming flow

---

## 1. Goal

Move the Claude Code agent that builds App Builder apps off the orchestrator container onto a **dedicated Hetzner VM with its own scoped identity**, and prove the architecture by giving the agent **one real-world capability** the current setup cannot: pulling **real flight data** into the `flight-booking` template via a Model Context Protocol (MCP) server wrapping the Duffel sandbox API.

The user's framing (from standup, 2026-05-11):

> *"You know open claw run things from machine scrape for flights project to the next level capabilities its good thing to research open claw different project … I would want it to be a separate computer from all of ours, because I don't trust the OpenClaw with Ralph's data … I would want to create a specific account for OpenClaw, and if anything goes wrong, we know that exactly where it went wrong."*

> *"With Open Claw, would just tell it what it needs to do. And I wouldn't need to search for the APIs for the flights, none of these things. It would do those things for me."*

Locked decisions from brainstorming (2026-05-12):

1. **Path A — augment, not replace.** Keep Claude Code as the brain. Add a `RemoteExecutor` backend that runs it on a separate VM. OpenHands / OpenCode become future plug-ins behind the same interface.
2. **Persistent shared Hetzner VM.** One CAX21 (~€7/mo), one Linux user `claude-agent`. Not ephemeral E2B sandboxes (revisit in v2 if scale demands).
3. **MVP scope: move + flight MCP demo.** One MCP server, one template wired to it. Not three MCPs.
4. **Shared dev API key for Duffel.** We hold one Duffel sandbox key in `.env`. BYO-key per tenant is a v2 concern.
5. **Rsync files back after `COMPLETED:`.** Built apps land on the orchestrator disk (as today). Preview pipeline unchanged.

---

## 2. Scope

### In scope

- One new Hetzner CAX21 VM provisioned, configured, and added to the project (private hostname: `claude-agent`).
- New code in the `tasks` service:
  - `mcp-servers/tasks/agent_executor.py` — factory + `BaseExecutor` interface
  - `mcp-servers/tasks/remote_executor.py` — SSH-based `RemoteExecutor` that runs Claude Code on the agent VM, streams stdout, rsyncs `apps/<slug>/` back
  - `mcp-servers/tasks/local_executor.py` — current `claude_executor.run_claude_subprocess` extracted behind the same interface; remains the default
  - Feature flag: `AGENT_BACKEND` env (`local` default; `remote` opt-in)
- One new MCP server: `mcp-servers/flights/` (stdio server, one tool `search_flights`, wraps Duffel sandbox API)
- Provisioning script: `scripts/provision_agent_vm.sh` (idempotent, one-shot)
- Smoke scripts: `scripts/smoke_agent_vm.sh`, `scripts/smoke_flights_mcp.sh`
- Unit + integration tests (see §6)
- Operator documentation: `docs/agent-vm/README.md` (provisioning, secret rotation, kill-switch, rollback)

### Out of scope

- Replacing Claude Code with OpenHands / OpenCode / Goose (path B / C from brainstorming — separate spec if/when prioritized).
- Ephemeral sandbox-per-task (E2B / Daytona / Cloudflare Sandbox) — revisit after MVP at-scale measurements.
- BYO-API-key flow per tenant for Duffel (requires credential broker + UI work).
- Additional MCP servers (maps, payments, scraping). Each is its own spec.
- Langfuse / OTel agent tracing — defer to v2 alongside fleet scaling.
- Concurrent multi-agent execution — orchestrator already serializes to one at a time; lift later.
- UI changes to the App Builder. Users see no new buttons, no new settings.
- Changes to the existing `flight-booking` template's static assets *except* the seed data file (so the agent can replace it with real flights without rewriting markup).

---

## 3. Architecture

### Three-layer stack

```
┌─────────────────────────────────────────────────┐
│ ORCHESTRATOR  (existing Hetzner VPS)            │
│ ai-ui.coolestdomain.win · 46.224.193.25         │
│                                                 │
│   tasks service · DB · Caddy · preview          │
│   serves /__public/<slug>/ from disk            │
│   AGENT_BACKEND=remote|local                    │
└──────────────────┬──────────────────────────────┘
                   │  SSH (key-only) + rsync over the internet
                   ▼  (private network if available in future)
┌─────────────────────────────────────────────────┐
│ AGENT VM  (NEW Hetzner CAX21, ~€7/mo)           │
│ private hostname: claude-agent                  │
│                                                 │
│   user: claude-agent (own scoped Linux user)    │
│   Claude Code CLI installed                     │
│   workspace: /agent/work/<task_id>/             │
│   MCP servers registered:                       │
│     - flights-mcp  (wraps Duffel sandbox)       │
└──────────────────┬──────────────────────────────┘
                   │  HTTPS
                   ▼
            api.duffel.com (sandbox)
```

### Why this shape

- **Sentinel-based one-shot subprocess contract preserved.** The orchestrator already parses `COMPLETED:` / `NEEDS_INPUT:` / `NEEDS_STEPS:` from streaming stdout (`claude_executor.py:729-778`). `RemoteExecutor` produces the same byte-stream over SSH. Zero changes to `routes_execution.py`'s sentinel handling.
- **Workspace boundary owned by orchestrator.** Built apps land on the orchestrator's `/workspace/ai_ui/apps/<slug>/` via rsync. Caddy `__public/<slug>/` route is unchanged. Preview, publish, and admin file-browsing all work identically.
- **Swappable backend.** `agent_executor.get_executor()` reads `AGENT_BACKEND` and returns the right implementation. Future executors (E2BExecutor, OpenHandsExecutor) implement the same `BaseExecutor.run(prompt, slug, execution_id) → AsyncIterator[str]` interface.

### Public interface every executor must honor

```python
class BaseExecutor(Protocol):
    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
    ) -> AsyncIterator[str]: ...
    # Yields stdout lines. Must include exactly one terminal sentinel
    # line (COMPLETED: / FAILED: / NEEDS_INPUT: / NEEDS_STEPS:) before
    # the stream closes. Respects EXECUTION_TIMEOUT_SECONDS (600s).

    async def stop(self, execution_id: str) -> None: ...
    # Cancels an in-flight run. Used by TaskStop endpoint.
```

This is the contract a replacement agent — Claude Code today, OpenHands tomorrow — must implement.

---

## 4. Components

### 4.1 Agent VM (`claude-agent` host)

**Provisioned from:** `scripts/provision_agent_vm.sh` (Bash, idempotent, runs from orchestrator).

| Spec | Value |
|---|---|
| Provider | Hetzner Cloud |
| SKU | CAX21 (4 vCPU ARM64, 8 GB RAM, 80 GB SSD) |
| Region | Same region as orchestrator (`fsn1` / Falkenstein) for latency |
| OS | Ubuntu 24.04 LTS |
| Cost | ~€7.50/mo + €0.60/mo primary IPv4 |
| User | `claude-agent` (uid 1001, no sudo, home `/home/claude-agent`) |
| Workspace | `/agent/work/` (chowned `claude-agent:claude-agent`, mode 0750) |
| Network ingress | ufw: `22/tcp` from orchestrator IP `46.224.193.25` only; all else deny |
| Network egress | unrestricted (Claude Code, MCP servers, Duffel all need it) |
| Hardening | SSH key-only (`PasswordAuthentication no`), `fail2ban`, automatic security updates |

**Installed software (by provision script):**
- Node.js 20 (NodeSource APT)
- Python 3.11 + `pip` + `venv`
- `@anthropic-ai/claude-code` CLI (`npm i -g`)
- `flights-mcp` (cloned from this repo, installed in `/opt/flights-mcp/`)
- `rsync`, `git`, `curl`, `jq` (for debugging)
- No Docker — kept boring.

**Secrets distribution:**
- `/home/claude-agent/.env` (mode 0600, owned `claude-agent`) contains:
  - `ANTHROPIC_API_KEY`
  - `DUFFEL_API_KEY`
- Provision script reads both from orchestrator's `.env` at provision time. The agent VM never receives the broader orchestrator secret bundle (Supabase, Fernet, Discord, etc.).
- Rotation: re-run provision script with new values; in-flight tasks complete on old key.

**MCP registration (in `/home/claude-agent/.claude.json`):**
```json
{
  "mcpServers": {
    "flights": {
      "command": "/opt/flights-mcp/venv/bin/python",
      "args": ["-m", "flights_mcp"],
      "env": { "DUFFEL_API_KEY": "${DUFFEL_API_KEY}" }
    }
  }
}
```

### 4.2 `BaseExecutor` interface (`mcp-servers/tasks/agent_executor.py`)

- `BaseExecutor` Protocol (signature above).
- `get_executor() -> BaseExecutor`: reads `AGENT_BACKEND` env; returns `LocalExecutor()` (default) or `RemoteExecutor()`. Unknown value raises `ValueError`, doesn't silently fall back.
- ~50 LOC. Pure factory + Protocol; no business logic.

### 4.3 `LocalExecutor` (`mcp-servers/tasks/local_executor.py`)

- Lifts the existing `claude_executor.run_claude_subprocess` body into a class method named `run`.
- Preserves: same args, same cwd, same env, same timeout, same sentinel emission.
- The existing `claude_executor.py` becomes a thin shim that calls `LocalExecutor().run(...)` (to minimize blast radius of the refactor; no callers move yet).
- `stop()` cancels the asyncio subprocess via `process.kill()`.

### 4.4 `RemoteExecutor` (`mcp-servers/tasks/remote_executor.py`)

**Required env:**
- `AGENT_HOST` — e.g. `claude-agent.io.internal`
- `AGENT_USER` — `claude-agent`
- `AGENT_SSH_KEY_PATH` — path to private key inside tasks container (`/run/secrets/agent_ssh_key`)

**`run()` algorithm:**

1. Pre-flight health check: `ssh -o ConnectTimeout=10 ... 'true'`. On failure → yield `"FAILED: agent_unreachable"` and return.
2. Build remote command:
   ```bash
   set -e
   TASK_DIR="/agent/work/<execution_id>"
   mkdir -p "$TASK_DIR" && cd "$TASK_DIR"
   # Pull current app state (if any) so agent has context for ENHANCE / NEEDS_INPUT resume
   rsync -az --delete <orch>:/workspace/ai_ui/apps/<slug>/ ./apps/<slug>/ || true
   claude --print --dangerously-skip-permissions \
          --output-format stream-json --verbose \
          -- "<prompt>"
   ```
   `<prompt>` is shell-quoted with `shlex.quote`.
3. `asyncio.create_subprocess_exec("ssh", "-i", AGENT_SSH_KEY_PATH, ..., remote_cmd)`. Stream stdout line-by-line; yield each line.
4. On `COMPLETED:` line (matched by existing regex): trigger `_rsync_back(slug, execution_id)` BEFORE yielding `COMPLETED:` onward (so orchestrator's later "list files" call sees them).
5. On `NEEDS_INPUT:` / `NEEDS_STEPS:` / `FAILED:`: yield and close.
6. On wall-clock timeout (600s): send `ssh ... 'pkill -u claude-agent -f claude'`, then yield `"FAILED: timeout"`.

**`_rsync_back(slug, execution_id)`:**
```
rsync -az --delete --chmod=D755,F644 \
  claude-agent@host:/agent/work/<execution_id>/apps/<slug>/ \
  /workspace/ai_ui/apps/<slug>/
```
After success: `ssh ... "rm -rf /agent/work/<execution_id>"` (best-effort; failure logged but not fatal).

**Post-rsync sanity check:** `apps/<slug>/index.html` must exist. If missing → mark task failed with `transport_error`, preserve agent VM workspace for debugging.

### 4.5 `flights-mcp` (`mcp-servers/flights/`)

**Layout:**
```
mcp-servers/flights/
├── flights_mcp/
│   ├── __init__.py
│   ├── __main__.py            ← stdio server entrypoint
│   ├── server.py              ← MCP Server + tool registration
│   ├── duffel.py              ← thin httpx wrapper for Duffel sandbox
│   └── schemas.py             ← pydantic in/out models
├── tests/
│   ├── test_server.py
│   └── test_duffel.py
├── pyproject.toml
└── README.md
```

**Single tool:**
```python
@server.tool()
async def search_flights(
    origin: str,             # IATA, e.g. "LAX"
    destination: str,        # IATA, e.g. "NRT"
    depart_date: str,        # ISO YYYY-MM-DD
    return_date: str | None = None,
    passengers: int = 1,
    cabin: Literal["economy","premium_economy","business","first"] = "economy",
) -> list[FlightOffer]: ...
```

**`FlightOffer` schema (returned to agent):**
```python
class FlightOffer(BaseModel):
    id: str
    airline: str             # marketing name, e.g. "All Nippon Airways"
    airline_code: str        # 2-letter IATA, e.g. "NH"
    flight_numbers: list[str]
    depart_airport: str      # IATA
    depart_time: str         # ISO 8601 with TZ
    arrive_airport: str
    arrive_time: str
    duration_minutes: int
    stops: int
    price_amount: float
    price_currency: str      # e.g. "USD"
    cabin: str
```

**Duffel mapping:** POST `/air/offer_requests` (synchronous), then GET `/air/offers?offer_request_id=...`. Take first 6 offers, sort by `total_amount` ASC. Defaults: `live_mode=false`, `Duffel-Version: v2`.

**Error mapping (returned as tool errors, not exceptions):**
- 401 / 403 → `{"error": "auth", "detail": "DUFFEL_API_KEY invalid"}`
- 422 → `{"error": "bad_request", "detail": <duffel message>}`
- 429 → `{"error": "rate_limit", "retry_after": <Retry-After header>}`
- 5xx → `{"error": "upstream", "detail": "duffel sandbox temporarily unavailable"}`
- network timeout (10s) → `{"error": "timeout"}`

Agent decides how to respond to tool errors. For `rate_limit` / `upstream` / `timeout`, it should fall back to the existing seed data array and emit `COMPLETED:` with a note in the result message ("real flights unavailable — used seed data"). This is normal Claude behavior; no special prompting required.

### 4.6 `flight-booking` template seed-data hook

**Tiny change to existing template** so the agent can replace seed data without touching markup:

`mcp-servers/tasks/template_apps/flight-booking/src/data.js` — exports `export const flights = [...30 seed flights...]`. Already exists. **No structural change** to this file; the agent overwrites the array contents (or the whole file) with real Duffel results, keeping the same `flights` named export. The rest of the template (`main.js` filter logic, UI, etc.) is untouched.

The prompt template (`build_prompt` in `tasks/prompts.py`) gets one new line for the `flight-booking` template: *"If you have access to a `search_flights` MCP tool, call it for the user's requested route and date, and replace the contents of `src/data.js` with the returned offers."*

---

## 5. Data flow

### 5.1 Happy path

```
User → POST /api/tasks
  body: { action_type:"BUILD", template_key:"flight-booking",
          slug:"flight-booker", description:"LAX→NRT June 1 for 2" }
  ↓
[orchestrator] DB: task row, status=pending
              shutil.copy2 template_apps/flight-booking → apps/flight-booker
              (unchanged from today)
  ↓
User → POST /api/tasks/{id}/execute
  ↓
[orchestrator] _run_execution(task_id, execution_id, prompt)
              get_executor() → RemoteExecutor (AGENT_BACKEND=remote)
  ↓
[orchestrator → agent VM via ssh]
  mkdir -p /agent/work/<eid>; cd /agent/work/<eid>
  rsync orchestrator:apps/flight-booker → ./apps/flight-booker
  claude --print ... -- "<prompt>"
  ↓
[agent VM] Claude Code reads template files
            decides to call `search_flights("LAX","NRT","2026-06-01",passengers=2)`
            flights-mcp → api.duffel.com sandbox
            returns 6 offers, sorted by price
            agent rewrites src/data.js with real offers
            agent emits "COMPLETED: Personalized with real LAX→NRT flights for 2"
  ↓
[orchestrator] receives COMPLETED line
              triggers _rsync_back:
                rsync agent-vm:/agent/work/<eid>/apps/flight-booker/
                      → /workspace/ai_ui/apps/flight-booker/
              sanity-check: apps/flight-booker/index.html exists ✓
              ssh agent-vm: rm -rf /agent/work/<eid>
              task → completed
  ↓
User refreshes preview → real ANA, JAL, United flights in the results list
URL: https://ai-ui.coolestdomain.win/__public/flight-booker/  (unchanged)
```

### 5.2 NEEDS_INPUT across the network

Identical to today's stateless re-run pattern:
- Agent emits `NEEDS_INPUT: <question>` → orchestrator parses → task → `awaiting_input` → SSH session ends.
- User replies via `POST /api/tasks/{id}/answer` → orchestrator builds new prompt with full `conversation_history` → re-issues `RemoteExecutor.run(...)` with the same `slug` → SSH opens, rsync re-syncs current workspace state, agent resumes.
- Workspace dir on agent VM is keyed by `slug` for resumes (`/agent/work/<slug>/`) — survives between turns of the same task; deleted only on terminal status.

Correction to §4.4 step 2: the remote `TASK_DIR` is keyed by `slug` (not `execution_id`) so resumes find the prior workspace. `execution_id` is used only for sentinel logging.

### 5.3 Failure modes

(Full table from §4 of brainstorming, retained here as reference.)

| Failure mode | Detection | Behavior |
|---|---|---|
| Agent VM unreachable | ssh exit ≠ 0 within 10s | Task → `failed` (`agent_unreachable`). Discord alert. No fallback to local (avoid hiding outages). |
| SSH disconnect mid-stream | stdout closes before terminal sentinel | Task → `failed`. Last 50 log lines preserved. Workspace on agent VM intact for forensics. Auto-retry once if attempts remain. |
| Agent timeout (>600s) | Existing wall-clock timer | `pkill -u claude-agent -f claude` via ssh. Task → `failed` (`timeout`). |
| rsync fails after COMPLETED | rsync exit ≠ 0 | Task → `failed` (`transport_error`). Files stay on agent VM. One automatic rsync retry. |
| rsync partial write | post-rsync `index.html` missing | Task → `failed`. Workspace preserved. |
| flights-mcp / Duffel 5xx / timeout | MCP tool error | Agent falls back to seed data, emits `COMPLETED:` with note. User sees usable app. |
| Duffel rate limit (429) | MCP tool error `{rate_limit, retry_after}` | Agent retries once after waiting, then falls back to seed data. |
| ANTHROPIC_API_KEY missing | Detected at provision time | Provision script fails loudly. Not a runtime concern. |
| Workspace state leak between tasks | Per-task subdir + `rm -rf` on terminal status | Daily cron on agent VM: `find /agent/work -mmin +1440 -delete`. |
| Agent VM disk fills | rsync `No space left` | Daily cron + Discord disk-usage alert. |
| User abandons `awaiting_input` task | Existing TTL | Same as today; no agent-VM resources held between turns. |

---

## 6. Testing

### 6.1 Unit (in repo, run on PR)

- `test_agent_executor_factory.py`
  - `AGENT_BACKEND=local` → returns `LocalExecutor`.
  - `AGENT_BACKEND=remote` → returns `RemoteExecutor`.
  - Unset → returns `LocalExecutor`.
  - `AGENT_BACKEND=garbage` → raises `ValueError`.
- `test_remote_executor.py` (mocks `asyncio.create_subprocess_exec`)
  - Feeds canned stream: `[..., "COMPLETED: ...", ""]` → yields all lines, triggers `_rsync_back`.
  - `NEEDS_INPUT: ...` → yields and closes; no rsync.
  - `FAILED: ...` → yields and closes; no rsync.
  - ssh connect failure (exit 255) → yields `FAILED: agent_unreachable`.
  - Wall-clock timeout → kills remote, yields `FAILED: timeout`.
  - Prompt with quotes/`$`/backticks shell-quoted correctly.
  - Approximately 10 cases.
- `test_flights_mcp.py` (mocks `httpx.AsyncClient`)
  - Happy path: returns 6 normalized offers, sorted by price ASC.
  - 401 → tool error `auth`.
  - 422 → tool error `bad_request`.
  - 429 with `Retry-After: 30` → tool error `rate_limit` with `retry_after=30`.
  - 503 → tool error `upstream`.
  - Network timeout → tool error `timeout`.
  - Malformed Duffel response (missing `total_amount`) → tool error `bad_response`.
  - Approximately 8 cases.

### 6.2 Integration (manual + scripted, before deploy)

- `scripts/smoke_agent_vm.sh` — provisioned VM checks:
  - ssh works as `claude-agent`
  - `claude --version` works
  - `ANTHROPIC_API_KEY` present in `/home/claude-agent/.env`
  - `DUFFEL_API_KEY` present
  - `flights-mcp` registered in `~/.claude.json` and `python -m flights_mcp --help` exits 0
  - `node --version` ≥ 20, `python3 --version` ≥ 3.11
- `scripts/smoke_flights_mcp.sh` — calls `search_flights("LAX","NRT","2026-06-01")` directly (no agent) and asserts ≥1 offer with non-empty `airline_code`. Hits real Duffel sandbox.

### 6.3 End-to-end (manual, gated demo)

- Pick `flight-booking` template, prompt: *"build me a booker for LAX to NRT June 1 for 2 people"*. Set `AGENT_BACKEND=remote`.
- Assert:
  - Task transitions: `pending` → `running` → `completed`
  - TaskExecution log contains a tool-call line for `search_flights`
  - `apps/<slug>/src/data.js` contains carrier names that do not appear in the original seed array (proves real Duffel data, not template fallback)
  - Preview loads at `/__public/<slug>/` and search UI returns ≥4 rows

### 6.4 Rollback verification

- Flip `AGENT_BACKEND=local`, repeat E2E with a non-flight template (e.g. `agency`). Build must succeed byte-identical to current production. This is the "did the refactor break anything?" guard.

### 6.5 Out of MVP test scope

- Load / concurrency (single-task-at-a-time today).
- Long-running agent VM uptime (rely on Hetzner monitoring + Discord disk alert).
- Adversarial prompt injection through Duffel responses (real concern; deferred to v2 with Langfuse + structured-output validation).

---

## 7. Security + ops

### 7.1 Identity & access

- Agent VM has one non-root user: `claude-agent`. No sudo, no docker group.
- SSH ingress: key-only. Single authorized key whose private half lives in the tasks container as a Docker secret at `/run/secrets/agent_ssh_key`, mode 0400.
- `ufw` on agent VM: inbound `22/tcp` from orchestrator IP only.
- No public services on the agent VM.

### 7.2 Secret distribution

- `/home/claude-agent/.env` written at provision time, mode 0600, owned by `claude-agent`.
- Contains: `ANTHROPIC_API_KEY`, `DUFFEL_API_KEY`. Nothing else.
- Agent VM never receives Supabase, Fernet, Discord, or other orchestrator secrets.
- Rotation: re-run `scripts/provision_agent_vm.sh` with new env values; in-flight tasks complete on old key.

### 7.3 Blast radius limits

- Claude Code runs as `claude-agent` user with `--dangerously-skip-permissions`. The flag is necessary for agent autonomy but only grants the autonomy of an unprivileged user — destructive commands hit `/home/claude-agent/`, not the host.
- Orchestrator never trusts files coming back: rsync target is always a fresh slug-scoped directory; filename sanitization already enforced via existing `_SLUG_RE = re.compile(r"apps/([a-z0-9_-]+)/")`.
- Kill switch: orchestrator can issue `ssh claude-agent@host 'pkill -u claude-agent -f claude'` via the existing TaskStop endpoint.
- Cost cap: Anthropic API key for agent VM has a usage limit set in the Anthropic Console (initial: $50/day). Caps the runaway-token failure mode at the provider layer.

### 7.4 Audit

- TaskExecution log already captures every line streamed from the agent. Unchanged.
- New column on `task_executions`: `agent_host TEXT NULL` — forward-compat for future fleet. Populated by `RemoteExecutor` with `AGENT_HOST`.

### 7.5 Operations

- Agent VM is **cattle, not pets** — fully provisioned by script in <10 min from scratch. No state outside in-flight `/agent/work/<slug>/` task workspaces.
- Backups: none. Stateless.
- Monitoring: Hetzner uptime alert; Discord webhook from orchestrator on `agent_unreachable` health-check failure.
- Daily cron on agent VM: `find /agent/work -mindepth 1 -mmin +1440 -delete` (gc workspaces idle >24h).

---

## 8. Implementation order

Planned by the writing-plans skill in the follow-up plan doc. Rough sketch:

1. Refactor `claude_executor.run_claude_subprocess` → `LocalExecutor.run` (no behavior change). Add `BaseExecutor` Protocol + `get_executor` factory. Tests green. Deploy. **Zero-risk refactor, verifies factory wiring.**
2. Write `flights-mcp` Python package + tests. Standalone — no agent VM required yet. CI green.
3. Write `scripts/provision_agent_vm.sh`. Test against a throwaway Hetzner box. Iterate until smoke scripts pass.
4. Provision the real `claude-agent` VM. Run smoke scripts. SSH manually, run `claude --print --output-format stream-json -- "hello"` to verify Claude Code on the box.
5. Write `RemoteExecutor` + tests. CI green.
6. Wire `agent_executor` into `routes_execution.py`. Default `AGENT_BACKEND=local` so behavior is unchanged.
7. Deploy. Manually flip `AGENT_BACKEND=remote` for a single test build to verify E2E.
8. Add the one-line prompt augmentation for `flight-booking` template referencing `search_flights` tool.
9. Demo to Lukas: prompt "LAX → NRT June 1 for 2", show real flights in preview.
10. Document `docs/agent-vm/README.md`. Decide whether to leave `AGENT_BACKEND=remote` as the new default (recommend yes after a week of dual-mode observation).

---

## 9. Open questions for spec reviewer

- Is `--dangerously-skip-permissions` acceptable on a scoped Linux user with ufw + key-only ingress + cost cap, or should we wire up Claude Code's `allowed-tools` config for tighter file-write restrictions? (Current local executor already uses the flag; remote is no worse.)
- Should `RemoteExecutor` fail open (fall back to `LocalExecutor` if agent unreachable) or fail closed (mark task failed)? **Spec proposes fail closed** — silent fallbacks hide outages and produce confusing demos.
- Is per-slug workspace dir on the agent VM (`/agent/work/<slug>/`) the right key, or should it be `(slug, tenant_id)` once tenant isolation lands? **MVP picks slug; revisit with multi-tenant work.**
- Should we add an explicit `agent_host` column to `task_executions` now, or use a JSON metadata column? Spec proposes a dedicated column for query-ability.

---

## 10. Non-goals worth stating loudly

- **This is not a multi-tenant agent fleet.** One agent VM, one identity, one shared dev API key. Multi-tenant comes later.
- **This is not a benchmark of Claude Code vs OpenHands vs OpenCode.** Path A explicitly defers that. The interface makes it possible later without a rewrite.
- **This is not generic "agent on a machine" infrastructure.** It is the App Builder's agent on a dedicated machine. No reusable agent platform here.
- **This is not a credential broker.** The Duffel key is ours, not the customer's. BYO-key is a v2 spec.
- **This is not a permanent abandonment of `LocalExecutor`.** Local mode stays in the codebase as the rollback path and the dev-loop convenience for engineers without the agent VM credentials.
