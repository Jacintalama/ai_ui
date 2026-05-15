# Spec — MCP Access from the VM-Hosted App-Builder Agent

**Date:** 2026-05-15
**Status:** Draft — revision 1
**Branch:** `feat/vm-agent-flight-mcp`
**Predecessor:** [Spec — VM-hosted Agent + Flight MCP for the IO App Builder](2026-05-12-vm-agent-flight-mcp-design.md)
**Author:** brainstormed with the user via the superpowers/brainstorming flow

---

## 1. Goal

Give the isolated `claude-agent` (the "open-claw" agent on the same Hetzner host) the ability to call **all 11 services in `mcp-servers/`** as proper MCP tools during an app-builder run, using **the same JWT authentication** that browser users use today.

User framing (Lukas, standup 2026-05-14):

> *"It runs on the same server, so it has also access to the… Does it have access to the existing MCP servers with this authentication? That's right. That's a big plus that it can implement extra integrations, and it can also, when we already have it in the MCP servers, that can access that as well with this authentication system. I really think that makes it very strong where we can code with our MCP servers, and our open-claw agent can already use them."*

Today the agent has exactly **one** MCP registered: `flights` (real MCP protocol, stdio, `claude mcp add`). The other ten services in `mcp-servers/` (`tasks`, `gmail`, `gdrive`, `calendar`, `web-search`, `meetings`, `meeting-kb`, `dashboard`, `scheduler`, `excel-creator`) are FastAPI HTTP REST APIs trusted via `X-User-Email` / `X-User-Admin` headers from the API Gateway — they are not callable from `claude --print` as tools.

This spec closes that gap by adding a thin stdio MCP wrapper per backend that authenticates as the user who triggered the build.

Locked decisions from brainstorming (2026-05-15):

1. **All 11 services in scope** (user picked "All services in `mcp-servers/`").
2. **Pass-through user JWT** — the agent acts on behalf of the user who clicked Build, not a service account (user picked "Pass through the user's JWT").
3. **Same-host topology** — `claude-agent` runs as a separate uid on the orchestrator's Hetzner host (per project memory). Traffic from the agent reaches the API Gateway over the Docker bridge `172.22.0.1:8085` (the host-side port mapping; the gateway's container-internal port is 8080).
4. **One stdio MCP wrapper per service** (approach A) — not a single mega-wrapper, not OpenAPI auto-discovery.
5. **Purposeful tool curation** — each wrapper exposes a small, hand-picked set of high-value tools, not every backend route.
6. **Manual app-builder flow only** — heartbeat/cron-driven runs have no live user JWT and are explicitly deferred to a separate spec.
7. **Route MCP service prefixes through the API Gateway** (decided after plan-review-pass-1 surfaced a routing gap). Today `Caddyfile:182-209` direct-routes `/gmail/*`, `/gdrive/*`, `/calendar/*`, `/meetings/*` to the MCP services on port 8000, *bypassing the gateway entirely*. Backends fall back to `default@local` when `X-User-Email` is absent (`mcp-servers/gmail/main.py:151-153`). To make the spec's auth model real, Caddy is changed to forward these prefixes (and four more: `/web-search`, `/meeting-kb`, `/dashboard`, `/excel-creator`) through `api-gateway:8080`, and the gateway's `proxy_handler` gets matching branches. This also closes a pre-existing security gap where all browser users shared `default@local` gmail/gdrive/calendar tokens.

---

## 2. Scope

### In scope

- New package `mcp-servers/io-mcp-wrappers/`:
  - `io_mcp_base/` — shared `GatewayClient`, `build_server`, `GatewayError`
  - `gmail/`, `gdrive/`, `web_search/`, `calendar/`, `meetings/`, `meeting_kb/`, `dashboard/`, `excel_creator/` — one stdio wrapper each (8 wrappers; `scheduler` deferred — replaced by future heartbeat; `tasks` deferred to v2 — see out-of-scope)
  - `tests/` — unit tests for the shared base + per-wrapper handlers
- Orchestrator changes:
  - `mcp-servers/tasks/main.py` — read the user's JWT from the request session at build-trigger time
  - `mcp-servers/tasks/remote_executor.py` — accept `user_jwt` parameter on `run()`; forward via SSH `SendEnv=IO_USER_JWT`
- **Routing changes (added 2026-05-15 after plan-review-pass-1):**
  - `Caddyfile` — change the four existing direct MCP routes (`/gmail/*`, `/gdrive/*`, `/calendar/*`, `/meetings/*`) to forward through `api-gateway:8080`. Add four new `handle` blocks for `/web-search/*`, `/meeting-kb/*`, `/dashboard/*`, `/excel-creator/*`.
  - `api-gateway/main.py:proxy_handler` — add eight `elif` branches that strip the gateway-side prefix and forward to the corresponding backend service (`mcp-web-search:8000`, `mcp-gmail:8000`, `mcp-gdrive:8000`, `mcp-calendar:8000`, `mcp-meetings:8000`, `meeting-kb:8200`, `mcp-dashboard:8000`, `mcp-excel-creator:8000`), with `X-User-Email` injected from validated JWT/cookie as it already does for `/api/tasks/*`. The `io-tasks` wrapper continues to use the existing `/api/tasks/*` path (already gateway-routed).
- Agent VM changes via `scripts/provision_agent_vm.sh`:
  - Install `io-mcp-wrappers` as one Python package at `/opt/io-mcp/`
  - Append `IO_GATEWAY_URL=http://172.22.0.1:8085` to `/home/claude-agent/.profile`
  - Append `IO_USER_JWT` to `/etc/ssh/sshd_config`'s `AcceptEnv` list
  - Register each wrapper via `claude mcp add --scope user io-<svc> /opt/io-mcp/venv/bin/python -m io_mcp_<svc>`
- One end-to-end smoke script: `scripts/smoke_mcp_access.sh`
- Test additions to `mcp-servers/tasks/tests/test_remote_executor.py` for the new `SendEnv` flag

### Out of scope

- **Heartbeat / cron-driven builds.** No live user → no JWT → pass-through doesn't apply. Will be its own spec ([[project_open_claw_heartbeat]]).
- **`scheduler` wrapper.** Deferred — the heartbeat spec will subsume it.
- **Token refresh / rotation.** Builds run for 60-300 seconds; a 24h-lifetime JWT survives the build. If a build outlives the token, the agent gets `auth` errors from the tool and reports failure cleanly. Refresh logic only matters once heartbeat exists.
- **Auto-discovery / OpenAPI mirror.** Tool surfaces are curated by hand. New backend routes do not automatically become tools.
- **Per-tool scope restrictions on the JWT.** The agent acts with whatever scopes the triggering user has. No JWT down-scoping in v1.
- **Squid allowlist for the API Gateway domain.** Traffic stays on 172.22.0.1 (same-host Docker bridge); never leaves the box; Squid is not in the path. (The existing Squid egress-enforcement gap from [[project-vm-agent-flights]] is separately tracked.)
- **Backend changes.** Zero modifications to the 10 FastAPI services themselves. They continue to trust `X-User-Email` from the gateway exactly as today — what changes is that the gateway now sets it correctly for these prefixes (it didn't before, because Caddy bypassed the gateway).
- **Dangerous mutating endpoints.** Each wrapper deliberately omits delete/destructive routes (e.g., `tasks_delete_project`, `gmail_delete_message`) from its tool surface. The agent cannot call them.
- **`io-tasks` wrapper entirely (deferred to v2).** The `tasks` service IS the orchestrator. An agent calling its own orchestrator mid-build is recursive, and on closer inspection of the existing routes (`routes_projects.py` is mounted at `/api/projects` with no root `GET /` listing endpoint; `routes_tasks.py:105` exposes `GET /api/tasks` returning a flat task list) there is no clean read-only "list projects / get project" surface to wrap without either adding new endpoints or shaping the wrapper around `/api/tasks` in a way that conflates tasks with projects. None of Lukas's standup examples needed this — gmail, gdrive, calendar, web-search are the integrations he demonstrated. Defer to v2; revisit if a concrete agent use case emerges.
- **UI changes.** Users see no new buttons, no new settings.

---

## 3. Architecture

### Data flow (one build)

```
USER's browser                              claude-agent VM
─────────────                               (same Hetzner host, different uid)
  │ JWT in cookie                           ─────────────────────────────────
  ↓                                         claude --print (the agent process)
ORCHESTRATOR (tasks container)                  │
  │ extracts user JWT from session              │ spawns stdio subprocesses
  │                                             │ on first tool use
  │ ssh -o SendEnv=IO_USER_JWT ─────────►   io-gmail     io-gdrive     io-web-search   ...
  │  (per-build, in ssh session env)             │            │              │
  │                                              │ httpx + Authorization: Bearer $IO_USER_JWT
  │                                              ↓            ↓              ↓
  └───────────────────────────────────────►  API GATEWAY @ http://172.22.0.1:8085
                                                  │ validates JWT, injects X-User-Email
                                                  ↓
                                              gmail svc, gdrive svc, web-search svc, ...
```

### Key invariants

- **JWT lives only in process env, never on disk.** From the orchestrator's local variable → ssh subprocess env (via `SendEnv`) → agent shell env → claude env → MCP wrapper subprocess env → `Authorization` header.
- **No new auth path.** The agent's HTTP traffic enters the gateway exactly like a browser request. Backends do not change.
- **Same-host network path.** Traffic goes 172.22.0.1:8085 (Docker bridge), not public DNS. Squid is not in the path.
- **One wrapper process per service per build.** Claude spawns a wrapper subprocess on first tool use; the subprocess dies with the build's claude process. Wrappers do not share state across builds.

### Components added

```
mcp-servers/
  io-mcp-wrappers/                  # new package
    pyproject.toml                  # one package, N console_scripts
    io_mcp_base/
      __init__.py
      client.py                     # GatewayClient
      server.py                     # build_server(name, tools)
      errors.py                     # GatewayError
    gmail/__init__.py + __main__.py + tools.py
    gdrive/    ...
    web_search/...
    calendar/  ...
    tasks/     ...
    meetings/  ...
    meeting_kb/...
    dashboard/ ...
    excel_creator/...
    tests/
      test_gateway_client.py
      test_gmail_wrapper.py
      test_gdrive_wrapper.py
      ...
scripts/
  provision_agent_vm.sh             # extended — installs wrappers, registers via claude mcp add
  smoke_mcp_access.sh               # new — end-to-end smoke
mcp-servers/tasks/
  main.py                           # changed — extract user JWT, pass to RemoteExecutor.run()
  remote_executor.py                # changed — accept user_jwt, forward via SendEnv
  tests/
    test_remote_executor.py         # one new test for SendEnv plumbing
```

### Tool curation (initial set)

The plan phase will finalize, but the spec commits to *curated, not exhaustive*. Indicative:

| Wrapper | Tools (MCP-side name) | Gateway path → backend route |
|---|---|---|
| `io-web-search` | `web_search` | `/web-search/web_search` → `mcp-web-search:8000/web_search` |
| `io-gdrive` | `gdrive_search`, `gdrive_read_file`, `gdrive_list_files` | `/gdrive/gdrive_*` → `mcp-gdrive:8000` (prefix stripped) |
| `io-gmail` | `gmail_search`, `gmail_send`, `gmail_read` | `/gmail/gmail_*` → `mcp-gmail:8000` (prefix stripped) |
| `io-calendar` | `calendar_list_events`, `calendar_create_event` | `/calendar/calendar_*` → `mcp-calendar:8000` (prefix stripped) |
| `io-meetings` | `meetings_list`, `meetings_get` | `/meetings/`, `/meetings/{id}` → `mcp-meetings:8000` (prefix stripped) |
| `io-meeting-kb` | `meeting_kb_search`, `meeting_kb_get`, `meeting_kb_list` | `/meeting-kb/search_meetings` (etc.) → `meeting-kb:8200` (prefix stripped) |
| `io-dashboard` | `dashboard_create` | `/dashboard/create_simple_dashboard` → `mcp-dashboard:8000` (prefix stripped) |
| `io-excel-creator` | `excel_create_workbook` | `/excel-creator/create_simple_excel` → `mcp-excel-creator:8000` (prefix stripped) |

No `gmail_delete_message`, no destructive verbs anywhere in v1. `io-tasks` is deferred entirely (see §2).

---

## 4. JWT plumbing & secret hygiene

This is the section that addresses Lukas's specific standup concern: *"the error messages, sometimes it sends it to the internet."*

### Lifecycle (per build)

1. **Browser → orchestrator** — user's JWT arrives as `Authorization: Bearer <jwt>` after gateway validation. Orchestrator's `main.py` reads it from the request.
2. **Orchestrator → RemoteExecutor** — new signature: `remote_executor.run(prompt, slug, execution_id, user_jwt)`. Stored only in a local var; never written to a file, never logged.
3. **Orchestrator → agent VM** — existing `_stream()` already uses `ssh -o SendEnv=AIUI_AGENT_EFFORT`. Extend to `SendEnv=AIUI_AGENT_EFFORT,IO_USER_JWT`. The orchestrator sets `IO_USER_JWT` in the subprocess env for the ssh call. `sshd_config` on the agent VM appends `IO_USER_JWT` to its `AcceptEnv` line.
4. **Agent shell** — the existing remote command (`set -e; cd /agent/work/...; set -a; source ~/.env; set +a; ... claude --print ...`) inherits `IO_USER_JWT` from the SSH session env. **Not** sourced into `~/.env`.
5. **claude → MCP subprocess** — claude inherits agent shell env; the wrapper subprocess inherits from claude.
6. **MCP wrapper → gateway** — `GatewayClient` reads `os.environ["IO_USER_JWT"]` once at startup. Sent as `Authorization: Bearer …` on every httpx call. Gateway validates, injects `X-User-Email`, backend serves normally.

### Secret hygiene (defense in depth)

- **Wrapper logging policy** — `GatewayClient` logs to stderr at INFO: method, URL, status, latency. *Never* the Authorization header, *never* the JWT, *never* request/response bodies for endpoints flagged sensitive (gmail content, gdrive file content). Enforced in the base, not opt-in per-wrapper.
- **`GatewayError` scrubs headers** — constructor strips any `Authorization` header from `e.request.headers` before storing. `__str__` / `__repr__` overridden so stringifying the exception never includes a header. The handler in each wrapper returns a sanitized `TextContent` to claude — never the raw exception.
- **claude sees redacted errors only** — `{"error":"auth","detail":"gateway rejected token"}`, not the actual JWT string. Even if claude logs the tool response (which Lukas worried about), no secret leaks.
- **Process env is not in claude's transcript** — claude only logs what it reads/writes; env vars set before it started are not in the stream-json. Verified pattern: `DUFFEL_API_KEY` is set the same way today and never appears in the stream.

### JWT expiry mid-build

App-builder JWTs are 24h. Typical builds are 60-300s. v1 has **no refresh logic**. A build that outlives its token gets `{"error":"auth"}` for any tool call and the agent reports failure cleanly. Acceptable for v1; revisit when heartbeat exists.

---

## 5. Error handling

Three layers, each fails predictably.

### Layer 1 — Wrapper startup

- `IO_USER_JWT` missing or empty → wrapper writes one MCP error to stderr and exits 1. Claude sees the subprocess die on first tool call and gets a clean "MCP server failed to start" signal. Better than ten identical 401s.
- `IO_GATEWAY_URL` missing → same.

### Layer 2 — Per-request errors (`GatewayClient` → gateway)

| HTTP status | Retry? | Tool response to claude |
|---|---|---|
| 2xx | — | `{"ok": true, "data": ...}` |
| 401 / 403 | no | `{"error":"auth","detail":"gateway rejected token"}` |
| 404 | no | `{"error":"not_found"}` |
| 429 | no | `{"error":"rate_limit","retry_after": <secs>}` |
| 5xx | 1× after 1s | on 2nd failure: `{"error":"server","detail":"<status>"}` |
| network / 30s timeout | 1× | on 2nd failure: `{"error":"network"}` |

Mirrors the flights MCP's existing error envelope — consistent across all wrappers.

### Layer 3 — Wrapper handler errors

Uncaught exceptions in tool handlers → caught at top of `call_tool` → response is `{"error":"internal"}` (no traceback, no detail). Real traceback goes to stderr only; never to claude's stream.

### What we deliberately don't do

- **No exponential backoff** — at most one retry. Builds are time-bounded; long retry chains waste budget when failing fast is more useful for the agent.
- **No circuit breaker** — ~9 independent wrappers; not worth the complexity.
- **No tool-level fallback** — that's the agent's job, not the wrapper's.

### Cancellation

Existing `_kill_remote` already SIGTERMs the agent's claude process; that cascades to wrapper subprocesses; httpx's connection pool gets cleaned up by Python shutdown. No new code.

---

## 6. Testing

### Layer 1 — Shared base unit tests (`tests/test_gateway_client.py`)

- `IO_USER_JWT` missing → `RuntimeError` at construct time
- `IO_GATEWAY_URL` missing → `RuntimeError` at construct time
- 200 → parsed JSON returned
- 401 → `GatewayError(kind="auth")`, no retry
- 500 → one retry, then `GatewayError(kind="server")`
- timeout → one retry, then `GatewayError(kind="network")`
- 429 → no retry, `retry_after` parsed from header
- **Secret hygiene assertion (paranoid)** — construct a `GatewayError` from a request whose headers include `Authorization: Bearer secret-token-do-not-leak`; assert `"secret-token-do-not-leak" not in str(err)` and not in `repr(err)`
- **Log hygiene assertion** — capture stderr from a full request lifecycle; assert the JWT string never appears

These two paranoia tests are the secret-hygiene contract; once green, every wrapper inherits the protection.

### Layer 2 — Per-wrapper unit tests (`tests/test_<service>_wrapper.py`)

Per wrapper (~5-8 tests each, mocked `GatewayClient`):

- `list_tools()` returns the curated tool set with correct schemas
- Each tool handler calls the correct gateway path with the correct method and payload
- Auth error from gateway → `{"error":"auth"}` in `TextContent`
- Success → `{"ok": true, "data": ...}` in `TextContent`

No network, no real subprocess. Fast.

### Layer 3 — End-to-end on the agent VM (`scripts/smoke_mcp_access.sh`)

```
1. Run a fresh build from the orchestrator with a prompt forcing the
   agent to use at least 2 MCPs:
     "Search the web for 'duffel api status' and email the result
      summary to <test address>."
2. Watch the stream-json for:
     - tool_use events naming io-web-search AND io-gmail
     - tool_result events with {"ok": true, ...}
     - terminal `result` event with COMPLETED
3. Assert: rsync-back fires; apps/<slug>/ lands on the orchestrator;
   the test email arrives (verified via gmail API).
4. Negative path: same prompt with IO_USER_JWT=invalid; assert tool
   results contain {"error":"auth"}; agent reports failure WITHOUT
   leaking the token in the stream or stderr.
```

### Orchestrator-side regression test

`mcp-servers/tasks/tests/test_remote_executor.py` — one new test: `run(..., user_jwt=...)` invokes ssh with `SendEnv=AIUI_AGENT_EFFORT,IO_USER_JWT` and sets `IO_USER_JWT` in the subprocess env. Existing 17 tests unchanged.

### What we explicitly do not test

- The MCP SDK's own behavior
- The API Gateway's JWT validation (tested elsewhere)
- Each backend service's logic (tested per-service)
- Performance / load (premature for v1)

### TDD discipline

Per the `test-driven-development` skill: every wrapper's tests are written **before** its handler code. The shared `GatewayClient`'s tests shape its API in dialog with the implementation, because the secret-hygiene assertions there are the contract.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| JWT leaks into a wrapper's stderr log | Base-class logging policy + paranoid unit tests assert the token string is never in stderr |
| JWT leaks into a tool response to claude | `GatewayError.__str__` strips headers; handlers return sanitized envelopes; paranoid test |
| Build outlives JWT (24h) | Accept v1 limitation. Agent gets `auth` error and reports cleanly. Revisit at heartbeat. |
| Agent picks a destructive tool that wasn't curated out | Wrapper surface omits delete/cancel verbs. New backend routes do NOT auto-promote to tools. |
| Wrapper hangs and blocks the build | 30s httpx timeout; existing build-level timeout in `_stream` covers the rest |
| Backend treats `X-User-Email` as authoritative but agent traffic somehow bypasses gateway | Wrappers ONLY know `IO_GATEWAY_URL`. There is no code path to talk to a backend directly. |
| Same-host topology changes (agent moves to separate VM) | Spec assumes 172.22.0.1; if agent moves, `IO_GATEWAY_URL` becomes public DNS and Squid allowlist must include it. Tracked as a follow-up. |
| Browser flows that hit `/gmail/*` etc. break when those routes start going through the gateway | The gateway already accepts `token` cookie alongside Authorization headers (`api-gateway/main.py:330-334`), so cookie-based browser flows continue working. Test the OAuth callback paths (`/gmail/auth/google/callback`, etc.) explicitly — they must remain reachable without a bearer token. |
| The 9 new gateway branches add 9 surface areas where rate limiting / logging behavior changes | The gateway already applies one consistent rate-limit policy; adding new prefixes just brings them under that policy. Run the smoke test post-deploy to confirm no regression on legitimate browser usage. |

---

## 8. Open questions

1. **Long-running stream tools.** `web-search` may take >30s for some queries. Current timeout is 30s; may need to lift specifically for that wrapper. Decide in plan phase.
2. **`gdrive_read_file` size limits.** A user could ask the agent to read a 500MB drive file. Need a max-bytes cap in the wrapper (e.g., 5MB) to protect both the agent's context window and the gateway.

*(Resolved 2026-05-15: `tasks` wrapper recursion — `io-tasks` is read-only in v1; see §2 out-of-scope.)*

---

## 9. Implementation sequence (preview — full plan in writing-plans phase)

1. Shared base (`io_mcp_base/`) + tests — secret hygiene contract green first
2. Orchestrator JWT plumbing + `test_remote_executor.py` test
3. **Caddyfile + `api-gateway/main.py:proxy_handler` — route 8 MCP service prefixes through the gateway** (new step, prerequisite for the wrappers to authenticate). Deploy to Hetzner; verify existing browser flows still work; verify `curl -H 'Authorization: Bearer <jwt>' https://ai-ui.coolestdomain.win/web-search/web_search` reaches the backend with the right `X-User-Email`.
4. `provision_agent_vm.sh` extension + dry-run on agent VM
5. Wrappers in dependency order: `web_search` (simplest, no auth state) → `gdrive` → `gmail` → `calendar` → `meetings`, `meeting_kb`, `dashboard`, `excel_creator` (8 wrappers; `tasks` deferred per §2)
6. End-to-end smoke (`scripts/smoke_mcp_access.sh`) — must pass before merge
7. Update `docs/agent-vm/README.md` with the new env vars and wrapper registry

---

## 10. Success criteria

- All Layer-1 + Layer-2 unit tests green (>90% line coverage on `io_mcp_base/`)
- The two paranoid secret-hygiene tests are present and green
- `scripts/smoke_mcp_access.sh` passes end-to-end on the live agent VM, including the negative-path JWT-leak check
- `mcp-servers/tasks/tests/test_remote_executor.py` — 18 tests passing (17 existing + 1 new)
- A live build using `io-web-search` AND `io-gmail` produces the expected output and rsyncs back cleanly
- No JWT string appears in the orchestrator logs, the agent's stderr logs, or claude's stream-json for a successful build
