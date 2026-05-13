# Spec — VM-hosted Agent + Flight MCP for the IO App Builder

**Date:** 2026-05-12
**Status:** Draft — revision 3 (incorporates spec-review passes 1 and 2)
**Branch:** `feat/vm-agent-flight-mcp` (off `feat/functional-templates`)
**Hard prerequisite:** `feat/functional-templates` must be merged to `main` before §4.6 / §8 step 8 can run. That branch contributes the `flight-booking` template (currently unmerged at the time of writing).
**Author:** brainstormed with Lukas via the superpowers/brainstorming flow

---

## 1. Goal

Move the Claude Code agent that builds App Builder apps off the orchestrator container onto a **dedicated Hetzner VM with its own scoped identity**, and prove the architecture by giving the agent **one real-world capability** the current setup cannot: pulling **real flight data** into the `flight-booking` template via a Model Context Protocol (MCP) server wrapping the Duffel sandbox API.

User framing (standup, 2026-05-11):

> *"You know open claw run things from machine scrape for flights project to the next level capabilities … I would want it to be a separate computer from all of ours, because I don't trust the OpenClaw with Ralph's data … I would want to create a specific account for OpenClaw, and if anything goes wrong, we know that exactly where it went wrong."*

> *"With Open Claw, would just tell it what it needs to do. And I wouldn't need to search for the APIs for the flights, none of these things. It would do those things for me."*

Locked decisions from brainstorming (2026-05-12):

1. **Path A — augment, not replace.** Keep Claude Code as the brain. Add a `RemoteExecutor` backend that runs it on a separate VM. OpenHands / OpenCode become future plug-ins behind the same interface.
2. **Persistent shared Hetzner VM.** One CAX21 (~€7.50/mo + €0.60/mo IPv4), one Linux user `claude-agent`. Not ephemeral E2B sandboxes (revisit in v2 if scale demands).
3. **MVP scope: move + flight MCP demo.** One MCP server, one template wired to it. Not three MCPs.
4. **Shared dev API key for Duffel.** We hold one Duffel sandbox key in `.env`. BYO-key per tenant is a v2 concern.
5. **Rsync files back after `COMPLETED:`.** Built apps land on the orchestrator disk (as today). Preview pipeline unchanged.

---

## 2. Scope

### In scope

- One new Hetzner CAX21 VM provisioned, configured, and added to the project (private hostname: `claude-agent`).
- New code in the `tasks` service:
  - `mcp-servers/tasks/agent_executor.py` — factory + `BaseExecutor` Protocol
  - `mcp-servers/tasks/remote_executor.py` — SSH-based `RemoteExecutor` that runs Claude Code on the agent VM, streams stdout, rsyncs `apps/<slug>/` back
  - `mcp-servers/tasks/local_executor.py` — current `claude_executor.run_claude_subprocess` extracted behind the same interface; remains the default
  - Feature flag: `AGENT_BACKEND` env (`local` default; `remote` opt-in)
- Required `_SENTINEL_RE` update: add `FAILED` to the recognized terminal sentinels alongside `COMPLETED|NEEDS_INPUT|NEEDS_STEPS` (today the parser maps "no sentinel" to `failed` by coincidence; the spec requires `FAILED:` to be first-class so `RemoteExecutor` can signal transport-layer failures clearly).
- One new MCP server: `mcp-servers/flights/` (stdio server, one tool `search_flights`, wraps Duffel sandbox API)
- Provisioning script: `scripts/provision_agent_vm.sh` (idempotent, one-shot, runs from operator workstation against a fresh Hetzner box)
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
- Loop-mode (Superpowers-style) sentinels for `RemoteExecutor`. `CLARIFY_DONE:`, `PLAN:`, `TESTS_PASSED:`, `TESTS_FAILED:` (parsed in `claude_executor.py:734-740`) are currently used only by `_run_execution`'s VERIFY-step retry loop when `max_attempts > 1`. **MVP only supports single-attempt remote runs.** If a remote task needs retry/verify, the orchestrator falls back to `LocalExecutor` for that retry. The interface allows this; the spec defers the full streaming-loop port to v2.
- Changes to the existing `flight-booking` template's static assets *except* a complete rewrite of `src/data.js` per task (so the agent can replace seed flights with real Duffel offers without touching markup or `main.js`).

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
                   │  SSH (key-only) over Hetzner
                   │  Cloud Networks private link
                   ▼  (10.0.0.0/16, same project)
┌─────────────────────────────────────────────────┐
│ AGENT VM  (NEW Hetzner CAX21, ~€7.50/mo)        │
│ hostname: claude-agent                          │
│ private IP: 10.0.0.42 (example)                 │
│                                                 │
│   user: claude-agent (own scoped Linux user)    │
│   Claude Code CLI installed                     │
│   workspace: /agent/work/<slug>/                │
│   MCP servers registered:                       │
│     - flights-mcp  (wraps Duffel sandbox)       │
└──────────────────┬──────────────────────────────┘
                   │  HTTPS (egress allowlist)
                   ▼
        api.anthropic.com · api.duffel.com
       registry.npmjs.org · deb.nodesource.com
```

### Why this shape

- **Sentinel-based one-shot subprocess contract preserved.** Today the orchestrator parses `COMPLETED:` / `NEEDS_INPUT:` / `NEEDS_STEPS:` from streaming stdout (`claude_executor.py:729-732`), with everything else mapped to `failed` (line 770-771). `RemoteExecutor` produces the same byte-stream over SSH. The spec adds `FAILED:` to the recognized sentinel set so transport errors are first-class; this is a small backwards-compatible change to `_SENTINEL_RE` shipped in step 1 of §8.
- **Workspace boundary owned by orchestrator.** Built apps land on the orchestrator's `/workspace/ai_ui/apps/<slug>/` via rsync. Caddy `/__public/<slug>/` route is unchanged. Preview, publish, and admin file-browsing all work identically.
- **Swappable backend.** `agent_executor.get_executor()` reads `AGENT_BACKEND` and returns the right implementation. Future executors (`E2BExecutor`, `OpenHandsExecutor`) implement the same `BaseExecutor.run(...) → AsyncIterator[str]` interface.

### Public interface every executor must honor

```python
class BaseExecutor(Protocol):
    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
    ) -> AsyncIterator[str]: ...
    # Async generator. Yields stdout lines. Must include exactly one
    # terminal sentinel line before the stream closes:
    #   COMPLETED:   FAILED:   NEEDS_INPUT:   NEEDS_STEPS:
    # Respects EXECUTION_TIMEOUT_SECONDS (600s) — on timeout the
    # implementation MUST yield "FAILED: timeout" and stop the
    # underlying process before closing the stream.

    async def stop(self) -> None: ...
    # Cancels the in-flight run on THIS executor instance.
    # No-op if no run is active. Used by TaskStop endpoint.
    # Single-task-at-a-time today; one stop() per executor instance
    # is sufficient. Future concurrency lifts this constraint.
```

`stop()` is parameter-less because the orchestrator serializes to one task at a time (`_RUNNING: dict` in `routes_execution.py:55`) and executor instances are owned by `_stream_claude`'s call scope. The executor keeps the active subprocess on `self._proc` (Optional, default None). The existing `proc_holder: dict` pattern (`claude_executor.py:821, 865-866`) is migrated to `self._proc` during step 1 of §8 — call site in `routes_execution.py` updates to use `executor.stop()` instead of `proc_holder["proc"].kill()`.

---

## 4. Components

### 4.1 Agent VM (`claude-agent` host)

**Provisioned from:** `scripts/provision_agent_vm.sh` (Bash, idempotent, runs from operator workstation; orchestrator does NOT auto-provision).

| Spec | Value |
|---|---|
| Provider | Hetzner Cloud |
| SKU | CAX21 (4 vCPU ARM64, 8 GB RAM, 80 GB SSD) |
| Region | `fsn1` (Falkenstein) — same as orchestrator |
| OS | Ubuntu 24.04 LTS |
| Cost | €7.50/mo + €0.60/mo primary IPv4 = ~€8.10/mo total |
| Network | Attached to same Hetzner Cloud Network as orchestrator (10.0.0.0/16). Public IPv4 retained for outbound HTTPS only. |
| Hostname | `claude-agent` (resolvable via `/etc/hosts` on orchestrator pointing to private IP) |
| User | `claude-agent` (uid 1001, no sudo, no docker, home `/home/claude-agent`) |
| Workspace | `/agent/work/` (owned `claude-agent:claude-agent`, mode 0750) |
| Ingress | ufw: `22/tcp` from orchestrator private IP `10.0.0.x` only; all else deny |
| Egress | iptables OUTPUT allowlist (see §7.3) — `api.anthropic.com`, `api.duffel.com`, `registry.npmjs.org`, `deb.nodesource.com`, `pypi.org`, plus DNS to Hetzner resolver |
| Hardening | SSH key-only (`PasswordAuthentication no`, `PermitRootLogin no`), `fail2ban`, `unattended-upgrades` for security patches |

**Installed software (by provision script):**
- Node.js 20 (NodeSource APT)
- Python 3.11 + `pip` + `venv`
- `@anthropic-ai/claude-code` CLI (`npm i -g`)
- `flights-mcp` Python package (cloned from this repo, installed in `/opt/flights-mcp/venv`)
- `rsync`, `git`, `curl`, `jq` (for debugging)
- No Docker — kept boring.

**MCP registration:** Performed by provision script via the supported CLI tooling, not by hand-writing a config file:

```bash
sudo -u claude-agent claude mcp add --scope user flights \
  /opt/flights-mcp/venv/bin/python -m flights_mcp \
  --env DUFFEL_API_KEY="$DUFFEL_API_KEY"
```

This is the documented way to register a stdio MCP server in Claude Code; the exact config file path (`~/.claude.json` or otherwise) is an implementation detail of the CLI version installed. The provision script must `claude mcp list` after registration and fail loudly if `flights` is not present.

#### 4.1.1 SSH key lifecycle

**Generation.** During provisioning, operator runs on the orchestrator host:

```bash
ssh-keygen -t ed25519 -f ./agent_ssh_key -N "" -C "orchestrator→claude-agent"
```

producing `agent_ssh_key` (private) and `agent_ssh_key.pub` (public).

**Distribution.**
- Private half: written to orchestrator host at `/etc/proxy-server/agent_ssh_key` (mode 0400, owned `root:root`). Mounted into the `tasks` container as a docker-compose secret at `/run/secrets/agent_ssh_key` via this addition to `docker-compose.unified.yml`:
  ```yaml
  secrets:
    agent_ssh_key:
      file: /etc/proxy-server/agent_ssh_key
  services:
    tasks:
      secrets:
        - agent_ssh_key
  ```
  Compose-format file-backed secret (works in non-Swarm `docker compose`; verified against the project's existing single-host setup).
- Public half: provision script copies it to the agent VM during initial setup and appends to `/home/claude-agent/.ssh/authorized_keys` (mode 0600, owned `claude-agent`). Any subsequent re-provision overwrites `authorized_keys` with the current public-key file (single-key model, no rotation overlap).
- **Direction:** orchestrator→agent only. Agent VM holds no SSH credentials back to the orchestrator (see §4.4 — file transport is push-on-start, pull-on-completion, both initiated from the orchestrator).

**Rotation.** To rotate:
1. Wait for in-flight tasks to finish (orchestrator serializes; verify via `/api/tasks` query).
2. Regenerate keypair on orchestrator.
3. Re-run `scripts/provision_agent_vm.sh` — overwrites `authorized_keys` on agent VM with new public key.
4. Replace `/etc/proxy-server/agent_ssh_key` with new private key, mode 0400.
5. Restart `tasks` container.

Rotation is operator-driven, not automated. Documented in `docs/agent-vm/README.md`.

### 4.2 `BaseExecutor` interface (`mcp-servers/tasks/agent_executor.py`)

- `BaseExecutor` Protocol (signature in §3).
- `get_executor() -> BaseExecutor`: reads `AGENT_BACKEND` env; returns `LocalExecutor()` (default) or `RemoteExecutor()`. Unknown value raises `ValueError`, doesn't silently fall back.
- ~50 LOC. Pure factory + Protocol; no business logic.

### 4.3 `LocalExecutor` (`mcp-servers/tasks/local_executor.py`)

- Lifts the body of `claude_executor.run_claude_subprocess` (`claude_executor.py:821-894`) into a class method named `run`.
- Preserves: same args (`claude --print --dangerously-skip-permissions --output-format stream-json --verbose --effort $AIUI_AGENT_EFFORT -- "<prompt>"`), same cwd (`CLAUDE_SANDBOX_DIR or CLAUDE_WORKSPACE`), same env (`IS_SANDBOX=1`), same timeout (`EXECUTION_TIMEOUT_SECONDS`), same output-cap behavior (`MAX_LOG_BYTES`), same sentinel emission.
- Migrates the `proc_holder: dict` parameter to `self._proc: asyncio.subprocess.Process | None = None`. `stop()` calls `self._proc.kill()` if set.
- `claude_executor.run_claude_subprocess` is rewritten as a thin shim: `async for chunk in LocalExecutor().run(prompt, slug=None, execution_id="legacy"): yield chunk` — preserves call sites while the broader refactor lands. Removed in a follow-up cleanup commit after callers migrate to `agent_executor.get_executor()`.
- Call site in `routes_execution.py` (the `_stream_claude` function around `claude_executor.py` line 55-65) updates to construct an executor once per task, stash it on the `_RUNNING[task_id]` dict, and call `executor.stop()` from the TaskStop endpoint instead of `proc_holder["proc"].kill()`.

### 4.4 `RemoteExecutor` (`mcp-servers/tasks/remote_executor.py`)

**Required env:**
- `AGENT_HOST` — e.g. `claude-agent` (resolved via `/etc/hosts` to private IP)
- `AGENT_USER` — `claude-agent`
- `AGENT_SSH_KEY_PATH` — path to private key inside tasks container (`/run/secrets/agent_ssh_key`)

**Slug validation:**

```python
_VALID_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,80}$")
```

Matches the pattern used elsewhere in the codebase for inbound slugs (cf. `routes_projects.py:398`'s `^[a-z0-9][a-z0-9._-]{1,80}$`; we drop `.` to avoid traversal corner cases). **The extraction regex** `_SLUG_RE = re.compile(r"apps/([a-z0-9_-]+)/")` in `claude_executor.py:741` is for *parsing* slugs out of agent stdout — different purpose, do not reuse for validation. `RemoteExecutor.run` raises `ValueError` if `slug is not None and not _VALID_SLUG.fullmatch(slug)`. This is the trust boundary.

**Workspace key:** `/agent/work/<slug>/`. Survives between `NEEDS_INPUT` resumes (each resume is a new `TaskExecution` but the same `TaskItem`/slug). Cleanup is triggered when `TaskItem.status` becomes terminal (`completed` or `failed`), not per-`TaskExecution`. Orchestrator emits the cleanup ssh after rsync-back succeeds on `COMPLETED`, or after marking failed on terminal failure paths.

**`run()` algorithm:**

1. **Validate slug** (above). Raise `ValueError` on bad input — caller's bug, not a runtime path.
2. **Pre-flight health check:** `ssh -o ConnectTimeout=10 -i $AGENT_SSH_KEY_PATH $AGENT_USER@$AGENT_HOST true`. On non-zero exit → yield `"FAILED: agent_unreachable"` and close. Do NOT fall back to `LocalExecutor` (fail closed; see §9).
3. **Push current state to agent VM** (orchestrator → agent, using the orchestrator's existing SSH key into the agent — no reverse-direction key needed):
   ```bash
   ssh -i "$AGENT_SSH_KEY_PATH" "$AGENT_USER@$AGENT_HOST" \
     "mkdir -p /agent/work/<slug>/apps/<slug>"
   rsync -az --delete \
     -e "ssh -i $AGENT_SSH_KEY_PATH" \
     /workspace/ai_ui/apps/<slug>/ \
     "$AGENT_USER@$AGENT_HOST:/agent/work/<slug>/apps/<slug>/"
   ```
   This step is idempotent (a `NEEDS_INPUT` resume re-syncs whatever was on the orchestrator at the time of resume, picking up any operator-side edits).
4. **Build remote command.** Pass through `AIUI_AGENT_EFFORT` so remote runs match local effort tier:
   ```bash
   cd /agent/work/<slug>
   IS_SANDBOX=1 claude \
     --print --dangerously-skip-permissions \
     --output-format stream-json --verbose \
     --effort "$AIUI_AGENT_EFFORT" \
     -- "<prompt>"
   ```
   `<prompt>` and `<slug>` are shell-quoted with `shlex.quote`. `AIUI_AGENT_EFFORT` is forwarded via `ssh -o "SendEnv=AIUI_AGENT_EFFORT"` + matching `AcceptEnv` on the agent VM's `sshd_config` (provisioning step). **The agent VM never holds SSH credentials back to the orchestrator** — file flow is push (orchestrator→agent) on start, pull (orchestrator initiates rsync from agent) on `COMPLETED`. Both directions use the same single SSH key, oriented orchestrator→agent.
5. **Spawn ssh:** `proc = await asyncio.create_subprocess_exec("ssh", "-i", AGENT_SSH_KEY_PATH, "-o", "BatchMode=yes", "-o", "SendEnv=AIUI_AGENT_EFFORT", f"{AGENT_USER}@{AGENT_HOST}", remote_cmd)`. Stash on `self._proc`. Stream stdout line-by-line; yield each line. Same `MAX_LOG_BYTES` cap as `LocalExecutor`.
6. **On `COMPLETED:` line** (matched by updated `_SENTINEL_RE`): trigger `_rsync_back(slug)` synchronously **before** yielding the `COMPLETED:` line, then yield it, then close. (Order matters — orchestrator's parser triggers `/api/tasks/{id}/files` listing as soon as it sees `COMPLETED:`; the rsync MUST be done before that lookup.)
7. **On `NEEDS_INPUT:` / `NEEDS_STEPS:` / `FAILED:`:** yield and close. Do NOT rsync back (workspace stays on agent VM for resume / forensics).
8. **On wall-clock timeout (600s):** issue `ssh ... 'pkill -u claude-agent -f "claude --print"'` (more specific than blanket `pkill claude` — only kills our build process, not any future concurrent ones), then yield `"FAILED: timeout"` and close.
9. **On `self._proc` killed externally by `stop()`:** propagate `CancelledError` to caller.

**`_rsync_back(slug)`:**

```bash
rsync -az --delete --chmod=D755,F644 \
  -e "ssh -i $AGENT_SSH_KEY_PATH" \
  $AGENT_USER@$AGENT_HOST:/agent/work/$slug/apps/$slug/ \
  /workspace/ai_ui/apps/$slug/
```

After rsync exit 0: `ssh ... "rm -rf /agent/work/$slug"` (best-effort; failure logged, not fatal — daily cron picks up leftovers).
After rsync non-zero: task → `failed` (`transport_error`), workspace preserved on agent VM. One automatic rsync retry; if it fails twice, surface the error.

**Post-rsync sanity check:** `/workspace/ai_ui/apps/<slug>/index.html` must exist. If missing → task → `failed` (`transport_error`), workspace preserved.

**File permission match:** the `--chmod=D755,F644` flags above match what `shutil.copy2` produces for the existing template-copy step. Verified equivalent with `stat` on existing `apps/` directories.

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
    id: str                    # Duffel offer ID
    origin: str                # IATA, e.g. "LAX"
    destination: str           # IATA, e.g. "NRT"
    airline: str               # marketing name, e.g. "All Nippon Airways"
    price: float               # USD amount
    stops: int
    duration: int              # minutes
    departure_hour: int        # 0-23, local airport tz
    departure_label: str       # "HH:MM"
    arrival_label: str         # "HH:MM"
    cabin: Literal["Economy","Premium Economy","Business","First"]
    baggage: str               # e.g. "1× 23kg checked"
```

This schema **matches the existing `flight-booking` template's `flight` shape** (`feat/functional-templates:mcp-servers/tasks/template_apps/flight-booking/src/data.js` lines 47-62) so the agent can replace the seed array without touching `main.js`. Required existing fields: `id, origin, destination, airline, price, stops, duration, departureHour, departureBucket, departureLabel, arrivalLabel, cabin, baggage`. The MCP returns `departure_hour` (snake_case Python); the agent transforms case at write time. `departureBucket` (early/morning/afternoon/evening) is computed in the template's data.js — the agent regenerates it using the same `bucketize` helper.

**Duffel mapping (Duffel field → FlightOffer field):**

| FlightOffer | Duffel source | Notes |
|---|---|---|
| `id` | `offer.id` | Direct |
| `origin` | `offer.slices[0].origin.iata_code` | First slice origin |
| `destination` | `offer.slices[0].destination.iata_code` | Last slice destination of trip |
| `airline` | `offer.owner.name` | "All Nippon Airways" |
| `price` | `float(offer.total_amount)` | Currency conversion to USD if `offer.total_currency != "USD"` — sandbox quotes in USD so MVP asserts USD and errors otherwise |
| `stops` | `len(offer.slices[0].segments) - 1` | Direct = 0 |
| `duration` | parse `offer.slices[0].duration` (ISO 8601 PT8H30M) → minutes | Helper in `duffel.py` |
| `departure_hour` | parse `offer.slices[0].segments[0].departing_at` → `.hour` | Local tz from airport |
| `departure_label` | format `departing_at` as `HH:MM` | Local tz |
| `arrival_label` | format `arriving_at` as `HH:MM` | Local tz, last segment |
| `cabin` | `offer.slices[0].segments[0].passengers[0].cabin_class` → title case | "economy" → "Economy" |
| `baggage` | construct from `offer.slices[0].segments[0].passengers[0].baggages` | Pluralize: `"1× 23kg checked"` |

**Duffel API call:** POST `/air/offer_requests?return_offers=true` (single call, sandbox supports it) with `Duffel-Version: v2`. Take first 6 offers from response, sort by `total_amount` ASC. If `return_offers=true` is rejected by the sandbox tier (verify at smoke time), fall back to two-step: POST `/air/offer_requests` then GET `/air/offers?offer_request_id=...`.

**Error mapping (returned as MCP tool errors):**

- 401 / 403 → `{"error": "auth", "detail": "DUFFEL_API_KEY invalid"}`
- 422 → `{"error": "bad_request", "detail": <duffel message>}`
- 429 → `{"error": "rate_limit", "retry_after": <Retry-After header or 60>}`
- 5xx → `{"error": "upstream", "detail": "duffel sandbox temporarily unavailable"}`
- network timeout (10s) → `{"error": "timeout"}`
- malformed response (missing required field) → `{"error": "bad_response", "detail": <field name>}`

Agent decides how to respond to tool errors. For `rate_limit` / `upstream` / `timeout`, agent should fall back to seed data and emit `COMPLETED:` with a note ("real flights unavailable — used seed data"). Standard Claude behavior; no special prompting required.

### 4.6 `flight-booking` template prompt augmentation

**Prerequisite:** `feat/functional-templates` merged. The `flight-booking` template lives at `mcp-servers/tasks/template_apps/flight-booking/` (introduced by commit `faa84f95e` on `feat/functional-templates`).

**Existing data shape** (`src/data.js`, lines 1-62 on `feat/functional-templates`):
- Three named exports: `airlines` (string array), `cities` (array of `{code, label}`), `flights` (computed from `routes.map(...)` over four parallel seed arrays).
- `flights` per-item schema documented in §4.5.
- Consumers in `src/main.js`: imports `{ flights, cities, airlines }`, reads every field listed above.

**Change:** the agent rewrites `src/data.js` entirely per task. The MCP returns flight data; the agent generates new `airlines`, `cities`, and `flights` arrays matching the existing exports. `cities` is derived from the unique IATA codes in the returned offers plus a humanized label. `airlines` is derived from unique airline names. `flights` is the offer list mapped to the existing schema.

**Prompt augmentation location:** `mcp-servers/tasks/claude_executor.py`, function `build_prompt` (around line 305 — the kitchen-sink module; **not** a separate `prompts.py`). The augmentation is a single conditional block added inside `build_prompt`:

```python
if template_key == "flight-booking":
    prompt += textwrap.dedent("""

        ## Real flight data
        You have access to a `search_flights` MCP tool that returns
        real flight offers from the Duffel sandbox API. If the user's
        request mentions specific airports, cities, or dates, call this
        tool and rewrite `src/data.js` so the `flights` named export
        contains the returned offers. Preserve the existing schema
        (`id, origin, destination, airline, price, stops, duration,
        departureHour, departureBucket, departureLabel, arrivalLabel,
        cabin, baggage`) so `src/main.js` continues to work. Re-derive
        `cities` and `airlines` from the offers. If the tool returns an
        error or no offers, leave the seed data and add a comment.
    """)
```

This is the only `build_prompt` change in this spec. The augmentation is harmless under `AGENT_BACKEND=local` (the tool simply isn't registered locally; Claude treats the prompt as advisory and falls back to seed data).

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
              executor stored on _RUNNING[task_id] for stop()
  ↓
[orchestrator → agent VM]
  push: rsync /workspace/ai_ui/apps/flight-booker/
              → agent-vm:/agent/work/flight-booker/apps/flight-booker/
  ssh:  cd /agent/work/flight-booker &&
        AIUI_AGENT_EFFORT=low claude --print ... --effort low -- "<prompt>"
  ↓
[agent VM] Claude Code reads template files
            decides to call search_flights("LAX","NRT","2026-06-01",
                                            passengers=2)
            flights-mcp → api.duffel.com sandbox (return_offers=true)
            returns 6 offers, sorted by price
            agent rewrites src/data.js with real offers
            agent emits "COMPLETED: Personalized with real LAX→NRT
                         flights for 2"
  ↓
[RemoteExecutor] sees COMPLETED in stream
                 BEFORE yielding it onward:
                   rsync -az --delete \
                     agent-vm:/agent/work/flight-booker/apps/flight-booker/
                     → /workspace/ai_ui/apps/flight-booker/
                   sanity: apps/flight-booker/index.html exists ✓
                   ssh agent-vm: rm -rf /agent/work/flight-booker
                 THEN yields "COMPLETED: ..." to orchestrator
[orchestrator] parses sentinel (now recognized by updated _SENTINEL_RE)
              task → completed (files are already on disk)
  ↓
User refreshes preview → real ANA, JAL, United flights in results
URL: https://ai-ui.coolestdomain.win/__public/flight-booker/  (unchanged)
```

### 5.2 NEEDS_INPUT across the network

Identical to today's stateless re-run pattern:
- Agent emits `NEEDS_INPUT: <question>` → orchestrator parses → task → `awaiting_input` → SSH session ends (no rsync-back).
- Workspace dir `/agent/work/<slug>/` is preserved on agent VM for the lifetime of the `TaskItem`.
- User replies via `POST /api/tasks/{id}/answer` → orchestrator builds new prompt with full `conversation_history` → re-issues `RemoteExecutor.run(...)` with the same `slug` → SSH opens, the `mkdir -p && rsync` step is a no-op (workspace exists), agent resumes with prior context.
- Workspace dir deleted only when `TaskItem.status` becomes `completed` (after rsync-back) or `failed` (immediately after marking failed). Daily gc cron picks up orphans older than 7 days (see §7.5).

### 5.3 Failure modes

| Failure mode | Detection | Behavior |
|---|---|---|
| Agent VM unreachable | ssh exit ≠ 0 within 10s | Task → `failed` (`FAILED: agent_unreachable`). Discord alert. No fallback to local (avoid hiding outages). |
| SSH disconnect mid-stream | stdout closes before terminal sentinel | Task → `failed`. Last 50 log lines preserved. Workspace on agent VM intact for forensics. Auto-retry once if attempts remain (uses `LocalExecutor` for retry per §2 loop-mode-out-of-scope rule). |
| Agent timeout (>600s) | Existing wall-clock timer | `pkill -u claude-agent -f "claude --print"` via ssh. Task → `failed` (`FAILED: timeout`). Workspace preserved. |
| rsync fails after COMPLETED | rsync exit ≠ 0 | Task → `failed` (`FAILED: transport_error`). Files stay on agent VM. One automatic rsync retry. |
| rsync partial write | post-rsync `index.html` missing | Task → `failed` (`FAILED: transport_error`). Workspace preserved. |
| flights-mcp / Duffel 5xx / timeout | MCP tool error | Agent falls back to seed data, emits `COMPLETED:` with note. User sees usable app. |
| Duffel rate limit (429) | MCP tool error `{rate_limit, retry_after}` | Agent retries once after waiting, then falls back to seed data. |
| ANTHROPIC_API_KEY missing | Detected at provision time | Provision script fails loudly. Not a runtime concern. |
| Workspace state leak between tasks | Per-slug subdir + `rm -rf` on terminal `TaskItem.status` | Daily cron on agent VM gc's orphans >7 days (long window protects `awaiting_input` resumes). |
| Agent VM disk fills | rsync `No space left` | Daily cron + Discord disk-usage alert. |
| User abandons `awaiting_input` task | Existing TaskItem TTL (90 days; unchanged) | Workspace persists up to TTL; gc cron's 7-day window deletes orphans where `TaskItem.status not in ('pending','running','awaiting_input')`. |

---

## 6. Testing

### 6.1 Unit (in repo, run on PR)

- `test_agent_executor_factory.py`
  - `AGENT_BACKEND=local` → returns `LocalExecutor`.
  - `AGENT_BACKEND=remote` → returns `RemoteExecutor`.
  - Unset → returns `LocalExecutor`.
  - `AGENT_BACKEND=garbage` → raises `ValueError`.
- `test_local_executor.py` (regression coverage for the refactor; mocks `asyncio.create_subprocess_exec`)
  - `stop()` kills `self._proc` if set, no-op otherwise.
  - Yields all stdout chunks until subprocess exits.
  - Output cap (`MAX_LOG_BYTES`) terminates the loop and yields the cap message.
  - Wall-clock timeout yields the timeout message.
  - `AIUI_AGENT_EFFORT` env propagated to `--effort` flag.
- `test_remote_executor.py` (mocks `asyncio.create_subprocess_exec` to simulate ssh)
  - Slug validation: valid → ok; invalid (`"../foo"`, `"bad..slug"`, empty, 100+ chars) → raises `ValueError`.
  - Canned stream `["foo", "COMPLETED: done", ""]` → yields all lines, triggers `_rsync_back` BEFORE closing.
  - `NEEDS_INPUT: ...` → yields and closes; no rsync.
  - `FAILED: ...` → yields and closes; no rsync.
  - ssh connect failure (exit 255) → yields `"FAILED: agent_unreachable"`.
  - Wall-clock timeout → kills remote, yields `"FAILED: timeout"`.
  - Prompt with quotes/`$`/backticks/newlines → shell-quoted correctly via `shlex.quote` (one case per shell metacharacter class).
  - `_rsync_back` exit ≠ 0 → retries once; if both fail, raises `TransportError`.
- `test_sentinel_parsing.py` (covers the `_SENTINEL_RE` update)
  - `FAILED: agent_unreachable` → `Outcome(kind="failed", payload="agent_unreachable")`.
  - Existing cases (`COMPLETED`, `NEEDS_INPUT`, `NEEDS_STEPS`, no-sentinel-text) unchanged.
- `test_flights_mcp.py` (mocks `httpx.AsyncClient`)
  - Happy path: returns 6 normalized offers, sorted by price ASC.
  - 401 → tool error `auth`.
  - 422 → tool error `bad_request`.
  - 429 with `Retry-After: 30` → tool error `rate_limit` with `retry_after=30`.
  - 503 → tool error `upstream`.
  - Network timeout → tool error `timeout`.
  - Malformed Duffel response (missing `total_amount`) → tool error `bad_response`.
  - Duffel field mapping: an ISO duration `PT8H45M` → `duration=525` minutes.

### 6.2 Integration (manual + scripted, before deploy)

- `scripts/smoke_agent_vm.sh` — provisioned VM checks:
  - ssh works as `claude-agent` using `/etc/proxy-server/agent_ssh_key`
  - `claude --version` works
  - `IS_SANDBOX=1 claude --print --dangerously-skip-permissions --effort low -- "say hello"` exits 0 within 30s
  - `ANTHROPIC_API_KEY` and `DUFFEL_API_KEY` present in `/home/claude-agent/.env`
  - `claude mcp list` includes `flights`
  - `node --version` ≥ 20, `python3 --version` ≥ 3.11
- `scripts/smoke_flights_mcp.sh` — runs flights-mcp over a stdio handshake (the right shape for an MCP server — not `--help`) and calls `search_flights("LAX","NRT","2026-06-01")` directly. Asserts ≥1 offer with non-empty `airline` and `price > 0`. Hits real Duffel sandbox.

### 6.3 End-to-end (manual, gated demo)

- Pick `flight-booking` template, prompt: *"build me a booker for LAX to NRT June 1 for 2 people"*. Set `AGENT_BACKEND=remote`.
- Assert:
  - Task transitions: `pending` → `running` → `completed`
  - TaskExecution log contains a tool-call line referencing `search_flights`
  - `apps/<slug>/src/data.js` contains airline names that do not appear in the original `airlines` seed array (proves real Duffel data, not template fallback). Specifically, none of: Skylane, Northwind, Aegis Air, Pacific Crest, Lumen Atlantic, Cirrus, Helios, Veridian.
  - Preview loads at `/__public/<slug>/` and search UI returns ≥4 rows.

### 6.4 Rollback verification

- Flip `AGENT_BACKEND=local`, repeat E2E with a non-flight template (e.g. `agency` from `feat/design-templates`). Build must succeed byte-identical to current production. This is the "did the refactor break anything?" guard.

### 6.5 Out of MVP test scope

- Load / concurrency (single-task-at-a-time today).
- Long-running agent VM uptime (rely on Hetzner monitoring + Discord disk alert).
- Adversarial prompt injection through Duffel responses (real concern; see §7.4 for accepted residual risk; full mitigation deferred to v2 with Langfuse + structured-output validation).

---

## 7. Security + ops

### 7.1 Identity & access

- Agent VM has one non-root user: `claude-agent`. No sudo, no docker group.
- SSH ingress: key-only. Single authorized key (lifecycle in §4.1.1). Private half is a docker-compose secret at `/run/secrets/agent_ssh_key`, mode 0400.
- `ufw` on agent VM: inbound `22/tcp` from orchestrator private IP only.
- No public services on the agent VM.

### 7.2 Secret distribution

- `/home/claude-agent/.env` written at provision time, mode 0600, owned by `claude-agent`.
- Contains: `ANTHROPIC_API_KEY`, `DUFFEL_API_KEY`. Nothing else.
- Agent VM never receives Supabase, Fernet, Discord, or other orchestrator secrets.
- Rotation: re-run `scripts/provision_agent_vm.sh` with new env values; in-flight tasks complete on old key (no overlap window — orchestrator serializes).

### 7.3 Egress allowlist (FQDN-based via local proxy)

Direct outbound HTTPS from `claude-agent` user is **denied by default** (iptables OUTPUT chain DROPs `tcp dport 443` for the `claude-agent` uid). All HTTPS egress is forced through a local Squid proxy listening on `127.0.0.1:3128`, configured with a domain-name allowlist:

```
# /etc/squid/squid.conf — minimal config installed by provision script
acl allowed_hosts dstdomain
  .anthropic.com
  .duffel.com
  .npmjs.org
  .nodesource.com
  .pypi.org
  .pythonhosted.org
  .ubuntu.com
http_access allow allowed_hosts
http_access deny all
http_port 3128
```

The `claude-agent` user has `HTTPS_PROXY=http://127.0.0.1:3128` and `HTTP_PROXY=http://127.0.0.1:3128` in its environment (`/home/claude-agent/.profile`). Squid resolves DNS per-request, so CDN rotations don't cause stale-allowlist failures. Also allowed at the kernel level (no proxy): DNS to Hetzner resolver (`185.12.64.1`, `185.12.64.2`) port 53 UDP/TCP — needed for Squid itself.

Rationale: even if a Duffel response or scraped page convinces the agent to `curl evil.com`, Squid 403s the request. FQDN-based is the right grain (no stale-IP failure mode); the proxy is a small additional component but uses ~30 MB RAM and has been boring for 25 years.

`apt-get install` on the agent VM uses `http://archive.ubuntu.com/` (port 80, not HTTPS) — apt's existing proxy config respects `Acquire::http::Proxy "http://127.0.0.1:3128"` set in `/etc/apt/apt.conf.d/95proxy`.

### 7.4 Blast radius limits + residual risks

- Claude Code runs as `claude-agent` user with `--dangerously-skip-permissions`. The flag is necessary for agent autonomy but only grants the autonomy of an unprivileged user — destructive commands hit `/home/claude-agent/`, not the host.
- Orchestrator never trusts files coming back: rsync target is always a fresh slug-scoped directory; **slug is strictly validated at the `RemoteExecutor` boundary** (`_VALID_SLUG` regex, §4.4) before being interpolated into shell or path arguments. This is the slug-injection mitigation.
- Kill switch: orchestrator can issue `ssh ... 'pkill -u claude-agent -f "claude --print"'` via the existing TaskStop endpoint.
- Cost cap: Anthropic API key for agent VM has a usage limit set in the Anthropic Console (initial: $50/day). Caps runaway-token failure mode at the provider layer.

**Accepted residual risks (documented for honesty, not silently absorbed):**

- **Prompt injection via Duffel response.** A malicious Duffel payload (carrier name like `"Skylane\"; rm -rf ~; #"`) could convince Claude to write outside `apps/<slug>/`. Mitigations in place: scoped Linux user limits damage to `/home/claude-agent/`; egress allowlist (§7.3) prevents data exfil to attacker-controlled hosts; rsync-back targets a strict slug-scoped path so files outside `apps/<slug>/` never reach the orchestrator. Full mitigation (structured-output validation, dual-LLM pattern) is deferred to v2.
- **Tool-call rate** is uncapped. Agent could call `search_flights` thousands of times in 10 minutes. Mitigations: Duffel's own 429 stops it; 600s wall-clock timeout caps damage; Anthropic cost cap caps spend. No per-tool rate limit in MVP.
- **Cross-task workspace inspection.** A malicious agent could `ls /agent/work/` and read another task's in-progress files. Single-tenant deployment makes this low-impact; multi-tenant deployment would need per-task chroot or container-per-task.

### 7.5 Audit

- TaskExecution log already captures every line streamed from the agent. Unchanged.
- New column on `task_executions`: `agent_host TEXT NULL`. Populated by `RemoteExecutor` with `AGENT_HOST`; null for `LocalExecutor`. Forward-compat for multi-VM fleet. Schema migration is one Alembic revision included in this PR.

### 7.6 Operations

- Agent VM is **cattle, not pets** — fully provisioned by script in <10 min from scratch. No state outside in-flight `/agent/work/<slug>/` task workspaces.
- Backups: none. Stateless.
- Monitoring: Hetzner uptime alert; Discord webhook from orchestrator on `agent_unreachable` health-check failure.
- **Workspace gc cron:** installed by provision script at `/etc/cron.d/agent-work-gc`, runs daily at 03:30 UTC:
  ```cron
  30 3 * * * claude-agent find /agent/work -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
  ```
  7-day window protects `awaiting_input` tasks that might resume after several days. Orchestrator's per-task cleanup (immediate on terminal status) handles the common case; cron is the belt-and-braces fallback for orphans (network failures mid-cleanup, etc.).
- **Squid log rotation:** `logrotate` rotates `/var/log/squid/access.log` daily, 14 days retained. Lets us audit "what did the agent try to reach?" after an incident.
- **No IP-refresh cron needed** — §7.3's FQDN-based proxy resolves DNS per-request.

---

## 8. Implementation order

Planned in detail by the writing-plans skill (next step). Rough sketch:

0. **Prerequisite:** merge `feat/functional-templates` to `main`. This brings in the `flight-booking` template that §4.6 / §6.3 reference. Without this step the demo path is impossible.
1. Refactor `claude_executor.run_claude_subprocess` → `LocalExecutor.run` (one file move + thin shim). Add `BaseExecutor` Protocol + `get_executor` factory. **Also update `_SENTINEL_RE` to include `FAILED`** and add a parser test. Adapt `_RUNNING` registry call site in `routes_execution.py` to use `executor.stop()` instead of `proc_holder["proc"].kill()`. Tests green. Deploy. **Low-risk-but-not-zero — cancellation contract changes.**
2. Write `flights-mcp` Python package + tests. Standalone — no agent VM required yet. CI green.
3. Write `scripts/provision_agent_vm.sh`. Test against a throwaway Hetzner box. Iterate until smoke scripts pass.
4. Generate SSH keypair (§4.1.1). Provision the real `claude-agent` VM. Run smoke scripts. SSH manually, run `IS_SANDBOX=1 claude --print --dangerously-skip-permissions --effort low -- "hello"` to verify Claude Code on the box.
5. Write `RemoteExecutor` + tests. CI green.
6. Wire `RemoteExecutor` into `agent_executor.get_executor()`. Default `AGENT_BACKEND=local` so behavior is unchanged on deploy.
7. Deploy. Manually flip `AGENT_BACKEND=remote` for a single test build to verify E2E.
8. Add the one-block prompt augmentation for `flight-booking` template (§4.6) inside `claude_executor.build_prompt`.
9. Demo to Lukas: prompt "LAX → NRT June 1 for 2", show real flights in preview.
10. Document `docs/agent-vm/README.md`. Decide whether to leave `AGENT_BACKEND=remote` as the new default (recommend yes after a week of dual-mode observation).

---

## 9. Open questions for spec reviewer (round 2)

- Is the egress allowlist of FQDNs (§7.3) the right grain, or should we tunnel all outbound traffic through a proxy on the orchestrator (more control, more failure points)?
- Should `_VALID_SLUG` (§4.4) live in a shared validators module so `routes_projects.py:398`'s similar-but-not-identical regex can be deduplicated? Or is the duplication intentional for trust-boundary clarity? Spec leaves it duplicated for clarity.
- The `_SENTINEL_RE` update to include `FAILED` (§3 / §8 step 1) changes behavior subtly: today, any agent text containing `FAILED: foo` is treated as failed only because no other sentinel matches. After the change, `FAILED:` anywhere in the stream is now first-class. Should we also add a `FAILED:` parse to the existing `Outcome` payload-extraction so `payload` contains the structured reason (`"agent_unreachable"`) instead of last-500-chars-of-text? Spec proposes yes.

---

## 10. Non-goals worth stating loudly

- **This is not a multi-tenant agent fleet.** One agent VM, one identity, one shared dev API key. Multi-tenant comes later.
- **This is not a benchmark of Claude Code vs OpenHands vs OpenCode.** Path A explicitly defers that. The interface makes it possible later without a rewrite.
- **This is not generic "agent on a machine" infrastructure.** It is the App Builder's agent on a dedicated machine. No reusable agent platform here.
- **This is not a credential broker.** The Duffel key is ours, not the customer's. BYO-key is a v2 spec.
- **This is not a permanent abandonment of `LocalExecutor`.** Local mode stays in the codebase as the rollback path and the dev-loop convenience for engineers without the agent VM credentials.
- **This is not a port of the Superpowers-style retry/verify loop to remote execution.** That requires streaming `CLARIFY_DONE:` / `PLAN:` / `TESTS_PASSED:` sentinels across the network and is out of scope (see §2).
