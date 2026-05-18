# Squid Egress Enforcement — Design

**Date:** 2026-05-18
**Branch:** `feat/vm-agent-flight-mcp`
**Status:** Approved (brainstormed with Lukas's standup as source)

## Problem

`scripts/provision_agent_vm.sh` step `[5/8]` already installs Squid on `127.0.0.1:3128` with an allowlist (`.anthropic.com`, `.duffel.com`, npm/pypi/ubuntu) and adds an iptables OUTPUT DROP rule for `claude-agent`'s outbound TCP 443. **But the agent can still reach arbitrary hosts in practice** because two things are broken:

1. **`HTTPS_PROXY` is written to `~/.profile`** — `.profile` only sources for *login* shells. The orchestrator's `ssh claude-agent@host claude --print …` runs as a non-interactive, non-login shell, so `.profile` is never sourced and `HTTPS_PROXY` is unset.
2. **The iptables DROP rule is not persisted** — `iptables-persistent` is not installed, so the rule survives in-memory only and disappears on reboot.

Net effect: traffic from `claude --print` builds bypasses Squid entirely. The Squid proxy exists but is decorative.

## Goal

Enforce that `claude-agent`'s outbound HTTPS traffic must go through Squid, where it's filtered by the allowlist. Out-of-allowlist hosts must be hard-blocked (TCP RST), not just routed-around.

Non-goals for v1: blocking outbound DNS, raw TCP to non-443 ports, or IPv6. Those are deferred to a future spec.

## Design

### Three changes to `scripts/provision_agent_vm.sh`

**A. Move proxy env into `~/.env`** (sourced by orchestrator before every build, plus by `.profile` for interactive sessions).

In step `[6/8]` where `.env` is written, add:

```
HTTPS_PROXY=http://127.0.0.1:3128
HTTP_PROXY=http://127.0.0.1:3128
NO_PROXY=127.0.0.1,localhost,172.22.0.1
```

`NO_PROXY` includes `172.22.0.1` so the io-mcp-wrappers' calls to the API Gateway (port 8085 on the docker host bridge) are NOT proxied — they go direct, otherwise Squid would block them as a non-allowlisted dest.

In step `[7b/8]` where the `claude mcp add` loop registers wrappers, leave the existing `IO_GATEWAY_URL` `-e` bake in place. Subprocess env var inheritance from Claude Code gives the wrappers `HTTPS_PROXY` automatically (Claude Code spreads `process.env` into each MCP spawn).

**B. Install and configure `iptables-persistent`** in step `[5/8]`:

```bash
DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
```

Then after the iptables OUTPUT rule is added:

```bash
iptables-save > /etc/iptables/rules.v4
```

(idempotent — same file overwritten on re-run with same rules)

**C. Add a smoke check at end of provision** verifying enforcement:

```bash
echo "==> [9/8] smoke: confirm Squid enforcement"
${SSH} sudo -u claude-agent bash -se <<'EOF'
set -euo pipefail
source ~/.env

# Allowed host must succeed (via Squid)
if ! curl -fsS -o /dev/null -m 10 https://api.anthropic.com/; then
  echo "FAIL: api.anthropic.com unreachable through Squid"
  exit 1
fi

# Disallowed host must fail (Squid blocks, then iptables blocks direct too)
if curl -fsS -o /dev/null -m 10 https://example.com/ 2>/dev/null; then
  echo "FAIL: example.com reachable — Squid not enforcing"
  exit 1
fi

echo "OK: squid enforcement verified"
EOF
```

### Test plan

1. **Unit-style assertion in provision smoke** — covered by [C] above. Runs at end of every provision.
2. **Manual repro before/after** — operator runs `ssh claude-agent@host 'source ~/.env && curl -m5 https://example.com'` — must hang/fail.
3. **Live e2e after deploy** — re-run `scripts/smoke_mcp_access.sh` with a real JWT to confirm the MCP wrappers still work through `NO_PROXY=172.22.0.1` (sanity: changing proxy config didn't break the existing happy path).

### Rollback

Revert step `[5/8]`'s `iptables` additions and remove the `HTTPS_PROXY` lines from `~/.env`. Squid keeps running but is no longer enforced. Acceptable safe state.

### Risk

- **NO_PROXY syntax pitfall** — curl/Python httpx accept `NO_PROXY=172.22.0.1,localhost`, but some tools require explicit `127.0.0.1`. Test both during smoke.
- **Squid restart loop** — if squid.conf has a syntax error, `systemctl reload squid` fails silently and old config keeps running. Smoke check [C] catches this because the disallowed-host test relies on fresh config.

## Files changed

- `scripts/provision_agent_vm.sh` — three edits as above
- (no application code changes; no new files)

## Acceptance

Provision smoke [C] passes on a re-provisioned agent VM. Live MCP smoke (existing `scripts/smoke_mcp_access.sh`) still succeeds.
