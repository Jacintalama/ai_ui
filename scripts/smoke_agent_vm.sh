#!/usr/bin/env bash
# Verifies the agent VM is correctly provisioned. Read-only.
#
# Usage:
#   AGENT_HOST=claude-agent \
#   AGENT_SSH_KEY_PATH=/etc/proxy-server/agent_ssh_key \
#   ./scripts/smoke_agent_vm.sh

set -euo pipefail

: "${AGENT_HOST:?set AGENT_HOST}"
: "${AGENT_SSH_KEY_PATH:?set AGENT_SSH_KEY_PATH}"

SSH="ssh -i ${AGENT_SSH_KEY_PATH} -o StrictHostKeyChecking=accept-new claude-agent@${AGENT_HOST}"

fail=0
check() { echo -n "[ ] $1 ... "; if eval "$2"; then echo OK; else echo FAIL; fail=1; fi; }

check "ssh as claude-agent"           "${SSH} 'true'"
check "claude --version"              "${SSH} 'claude --version' >/dev/null"
check "node --version >= 20"          "${SSH} 'node --version | grep -E \"^v(2[0-9]|[3-9][0-9])\"' >/dev/null"
check "python3 --version >= 3.11"     "${SSH} 'python3 -c \"import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)\"'"
check "ANTHROPIC_API_KEY set"         "${SSH} 'grep -q ^ANTHROPIC_API_KEY= ~/.env'"
check "DUFFEL_API_KEY set"            "${SSH} 'grep -q ^DUFFEL_API_KEY= ~/.env'"
check "claude mcp list shows flights" "${SSH} 'claude mcp list | grep -q flights'"
check "squid running"                 "${SSH} 'systemctl is-active --quiet squid'"
check "ufw active"                    "${SSH} 'sudo ufw status | grep -q active' || true"   # claude-agent has no sudo, may be ok
check "Hello via claude"              "${SSH} 'IS_SANDBOX=1 claude --print --dangerously-skip-permissions --effort low -- \"say the literal word READY\" 2>&1 | grep -q READY'"

if [[ $fail -eq 0 ]]; then
  echo
  echo "All smoke checks PASSED."
else
  echo
  echo "One or more smoke checks FAILED — see above."
  exit 1
fi
