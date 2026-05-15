# Agent VM

Isolated agent environment for running Claude builds with registered MCP access to backend services.

## MCP Wrappers (added 2026-05-15)

### What this is

The isolated `claude-agent` user runs `claude --print` builds with a set of stdio MCP wrappers registered via `claude mcp add`. Each wrapper is a thin Python module that translates `call_tool(...)` into an authenticated HTTP call to the API Gateway. The gateway validates the user's JWT and injects `X-User-Email` before forwarding to the matching backend (gmail, gdrive, calendar, etc.).

Spec: [docs/superpowers/specs/2026-05-15-mcp-access-from-vm-agent-design.md](../superpowers/specs/2026-05-15-mcp-access-from-vm-agent-design.md)

### Env vars

- `IO_GATEWAY_URL` — Set in `/home/claude-agent/.env` and baked into each io-* server's `env` block in `~/.claude.json` (value: `http://172.22.0.1:8085`). The agent VM runs on the orchestrator's Docker host; the api-gateway container exposes port 8080 internally and is published on the host bridge at port **8085**, so claude-agent (host user, not in a container) reaches the gateway at `172.22.0.1:8085`.
- `IO_USER_JWT` — Forwarded per-build by the orchestrator via SSH `SendEnv`. Lives only in process env during one build; never persisted to disk.

### Registered wrappers

Run `claude mcp list` as `claude-agent` to see all `io-*` wrappers. v1 ships 8:

| Wrapper | Backend service |
|---|---|
| `io-web-search` | Brave-backed web search via `mcp-web-search` |
| `io-gdrive` | Google Drive (search, read, list) |
| `io-gmail` | Gmail (search, read, send) |
| `io-calendar` | Google Calendar (list events, create event) |
| `io-meetings` | Meetings backend (list, get by id) |
| `io-meeting-kb` | Meeting knowledge base (search, get, list) |
| `io-dashboard` | Dashboard creator |
| `io-excel-creator` | Excel workbook creator |

Plus the existing `flights` MCP (Duffel sandbox).

### Common operator tasks

- **Add a new wrapper:**
  1. Create `mcp-servers/io-mcp-wrappers/io_mcp_<svc>/` following the `io_mcp_web_search` template (`__init__.py`, `tools.py`, `__main__.py`)
  2. Add tests under `tests/test_<svc>_wrapper.py`
  3. Append `<svc>` to the `for svc in ...` loop in `scripts/provision_agent_vm.sh` step `[7b/8]`
  4. Re-run provisioning

- **Verify JWT plumbing for a build:**
  ```bash
  ssh root@<agent-vm> journalctl -u ssh --since '10 min ago' | grep -i accept_env
  ```
  You should see `IO_USER_JWT` accepted by sshd during the build's SSH session.
  **The JWT value itself must NEVER appear in any log line.**

- **Manually run a wrapper from the agent VM:**
  ```bash
  ssh claude-agent@<agent-vm>
  source ~/.profile  # sets IO_GATEWAY_URL
  IO_USER_JWT=<a-real-jwt> python -m io_mcp_web_search
  # then send a `tools/list` MCP message over stdin
  ```

- **Smoke-test the end-to-end pipeline:**
  ```bash
  ORCH_HOST=<orchestrator-host> IO_USER_JWT=<real-jwt> \
    ./scripts/smoke_mcp_access.sh
  ```

### Out of scope (deferred to the heartbeat spec)

The MCP-access pipeline assumes a live user JWT. Cron / scheduled / no-live-user invocations don't carry one, so all wrappers will fail-fast with `auth` errors for those flows. The heartbeat feature ([[project_open_claw_heartbeat]] in memory) is a separate spec that will add either a refresh mechanism or service-account auth for the periodic case.

### Pre-existing fix landed alongside this

Before 2026-05-15, Caddy direct-routed `/gmail/*`, `/gdrive/*`, `/calendar/*`, `/meetings/*` to the MCP backends bypassing the API Gateway. The backends fell back to `default@local` when `X-User-Email` was absent, which meant all browser users implicitly shared one set of OAuth tokens per service. Task 10b in this PR fixes that — those 4 prefixes (plus 4 new ones for the wrappers) now go through the gateway with proper per-user `X-User-Email` injection.
