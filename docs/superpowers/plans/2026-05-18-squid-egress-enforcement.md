# Squid Egress Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Squid actually block claude-agent's outbound HTTPS to non-allowlisted hosts. Today the proxy exists but is decorative — `HTTPS_PROXY` lives in `.profile` (login-shells-only) and the iptables DROP rule isn't persisted.

**Architecture:** Three small, surgical edits to `scripts/provision_agent_vm.sh`. No application code changes. Verified by an end-of-provision smoke that requires `api.anthropic.com` reachable AND `example.com` unreachable.

**Tech Stack:** bash, ssh, iptables, iptables-persistent, squid (already installed).

**Spec:** `docs/superpowers/specs/2026-05-18-squid-egress-enforcement-design.md`

---

### Task 1: Move proxy env vars into `~/.env` so non-login shells see them

**Files:**
- Modify: `scripts/provision_agent_vm.sh` — step `[6/8]` (search for `secrets — /home/claude-agent/.env`)

- [ ] **Step 1: Read the current `[6/8]` block to confirm exact context**

Run: read `scripts/provision_agent_vm.sh` lines 145-155.
Expected: the `cat >>/home/claude-agent/.env <<INNER` block adding `ANTHROPIC_API_KEY`, `DUFFEL_API_KEY`, `IO_GATEWAY_URL`.

- [ ] **Step 2: Append three more lines to that heredoc**

Edit `scripts/provision_agent_vm.sh`. In the `INNER` heredoc of step `[6/8]`, after the `IO_GATEWAY_URL=...` line add:

```
HTTPS_PROXY=http://127.0.0.1:3128
HTTP_PROXY=http://127.0.0.1:3128
NO_PROXY=127.0.0.1,localhost,172.22.0.1
```

(`NO_PROXY=172.22.0.1` is critical — io-mcp-wrappers' calls to the API Gateway on `172.22.0.1:8085` must NOT be proxied through Squid, otherwise they'd be blocked as a non-allowlisted dest.)

- [ ] **Step 3: Remove the redundant HTTPS_PROXY block from `.profile`**

In step `[5/8]`, locate the `cat >/home/claude-agent/.profile <<'CONF'` block that writes `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY`. Delete the whole heredoc plus its `chown` line — `.env` is the single source of truth now.

(Leave the `IO_GATEWAY_URL` `.profile` append in step `[7b/8]` alone — that's a different file write, idempotent, harmless. Belt-and-braces.)

- [ ] **Step 4: Commit**

```
git add scripts/provision_agent_vm.sh
git commit -m "fix(provision): move HTTPS_PROXY to .env so non-login shells see it"
```

---

### Task 2: Install iptables-persistent and save the OUTPUT rule

**Files:**
- Modify: `scripts/provision_agent_vm.sh` — steps `[1/8]` and `[5/8]`

- [ ] **Step 1: Add `iptables-persistent` to the apt install list**

In step `[1/8]`, find the `DEBIAN_FRONTEND=noninteractive apt-get install -y \` block. Add `iptables-persistent` to the package list (keep the backslash line-continuations clean). Place it right after `squid`.

Note: `iptables-persistent` will prompt to save current rules during install, but `DEBIAN_FRONTEND=noninteractive` makes it accept defaults silently.

- [ ] **Step 2: Save the iptables rule at the end of step `[5/8]`**

After the `iptables -A OUTPUT -m owner --uid-owner claude-agent ...` line, add:

```
# Persist the OUTPUT rule across reboots — iptables-persistent reads this file
iptables-save > /etc/iptables/rules.v4
```

Idempotent: re-running the script overwrites the file with the current ruleset.

- [ ] **Step 3: Make the iptables append idempotent**

The current `iptables -A OUTPUT ...` line appends every time the script runs. Make it idempotent by checking first:

Replace the existing line:
```
iptables -A OUTPUT -m owner --uid-owner claude-agent \
  -p tcp --dport 443 ! -d 127.0.0.1 -j DROP
```

With:
```
# Idempotent — only add if rule doesn't already exist
if ! iptables -C OUTPUT -m owner --uid-owner claude-agent \
    -p tcp --dport 443 ! -d 127.0.0.1 -j DROP 2>/dev/null; then
  iptables -A OUTPUT -m owner --uid-owner claude-agent \
    -p tcp --dport 443 ! -d 127.0.0.1 -j DROP
fi
```

- [ ] **Step 4: Commit**

```
git add scripts/provision_agent_vm.sh
git commit -m "fix(provision): persist iptables OUTPUT rule + make idempotent"
```

---

### Task 3: Add end-of-provision smoke that asserts enforcement

**Files:**
- Modify: `scripts/provision_agent_vm.sh` — add new step `[9/8]` at end (before the final `echo "OK"`)

- [ ] **Step 1: Add the smoke block**

Right before the final `echo "OK — provisioning complete..."`, insert:

```bash
echo "==> [9/8] smoke: confirm Squid enforcement"
${SSH} sudo -u claude-agent bash -se <<'EOF'
set -euo pipefail
set -a; source ~/.env; set +a

# Allowed host must succeed (via Squid allowlist)
if ! curl -fsS -o /dev/null -m 10 https://api.anthropic.com/; then
  echo "FAIL: api.anthropic.com unreachable through Squid"
  exit 1
fi
echo "  ok: api.anthropic.com reachable"

# Disallowed host must fail (Squid denies; iptables drops direct)
if curl -fsS -o /dev/null -m 10 https://example.com/ 2>/dev/null; then
  echo "FAIL: example.com reachable — egress NOT enforced"
  exit 1
fi
echo "  ok: example.com blocked"

# Gateway must remain reachable via NO_PROXY direct route
if ! curl -fsS -o /dev/null -m 10 "http://${IO_GATEWAY_URL#http://}/healthz" 2>/dev/null; then
  echo "WARN: gateway healthz unreachable — may be expected if /healthz not added yet"
fi
echo "  squid enforcement smoke: PASS"
EOF
```

(The `set -a; source ~/.env; set +a` pattern matches the orchestrator's remote_executor pattern — same auto-export semantics.)

- [ ] **Step 2: Bump step numbers in earlier `echo` lines from `[N/8]` to `[N/9]`**

Search-and-replace `[1/8]` → `[1/9]`, `[2/8]` → `[2/9]`, …, `[8/8]` → `[8/9]`, then change the new step from `[9/8]` to `[9/9]`. Pure cosmetic; keep it tidy.

- [ ] **Step 3: Commit**

```
git add scripts/provision_agent_vm.sh
git commit -m "feat(provision): add Squid enforcement smoke at end of provision"
```

---

### Task 4: Live verification on the agent VM

> This is the "end-to-end no red marks" step. Cannot be skipped.

- [ ] **Step 1: Re-run provision on the existing agent VM**

Operator runs (from a workstation with the IO repo + SSH key):

```bash
AGENT_HOST=<agent-vm-ip> \
AGENT_SSH_KEY_PUB=/etc/proxy-server/agent_ssh_key.pub \
ANTHROPIC_API_KEY=<key> \
DUFFEL_API_KEY=<key> \
ORCHESTRATOR_PRIVATE_IP=10.0.0.10 \
  ./scripts/provision_agent_vm.sh
```

Expected: terminates with `[9/9] squid enforcement smoke: PASS` and `OK — provisioning complete`.

- [ ] **Step 2: Manual repro from a fresh ssh**

```bash
ssh claude-agent@<agent-vm> 'set -a; source ~/.env; set +a; curl -m5 https://example.com 2>&1; echo "exit=$?"'
```

Expected: timeout or connection refused; exit ≠ 0.

```bash
ssh claude-agent@<agent-vm> 'set -a; source ~/.env; set +a; curl -m5 -o /dev/null -w "%{http_code}\n" https://api.anthropic.com'
```

Expected: `200` or `401` (anthropic returns 401 to unauthenticated probes — that's fine, the point is the connection went through).

- [ ] **Step 3: Re-run the existing MCP smoke**

```bash
ORCH_HOST=<orchestrator-ip> IO_USER_JWT=<real-jwt> ./scripts/smoke_mcp_access.sh
```

Expected: completes successfully (proves the `NO_PROXY=172.22.0.1` direct-route to the gateway still works).

- [ ] **Step 4: Survive-reboot check**

```bash
ssh root@<agent-vm> reboot
# wait ~30 s
ssh root@<agent-vm> iptables -L OUTPUT -n | grep claude-agent
```

Expected: the DROP rule is present after reboot (proves `iptables-persistent` is working).

- [ ] **Step 5: Update memory file**

Edit `C:\Users\alama\.claude\projects\C--Users-alama-Desktop-Lukas-Work-IO\memory\project_vm_agent_flights.md`: remove the "Open gap — egress not enforced" section, replace with "Egress now enforced (2026-05-18)."
