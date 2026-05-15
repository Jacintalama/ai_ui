#!/usr/bin/env bash
# Provision a fresh Hetzner CAX21 (Ubuntu 24.04) as the IO claude-agent VM.
#
# Idempotent — re-running just refreshes config + rotates secrets.
#
# Usage:
#   AGENT_HOST=10.0.0.42 \
#   AGENT_SSH_KEY_PUB=/etc/proxy-server/agent_ssh_key.pub \
#   ANTHROPIC_API_KEY=sk-ant-... \
#   DUFFEL_API_KEY=duffel_test_... \
#   ORCHESTRATOR_PRIVATE_IP=10.0.0.10 \
#   ./scripts/provision_agent_vm.sh
#
# Optional:
#   OPERATOR_BOOTSTRAP_IP=203.0.113.42 — adds a TEMP ufw allow rule so the
#   operator's workstation isn't locked out mid-script. Remove manually
#   after smoke checks pass:
#     ssh root@<agent> "ufw status numbered" && ssh root@<agent> "ufw delete N"
#
# Prerequisites on the operator workstation:
#   - SSH access to the box as root (via initial cloud-init key)
#   - The IO repo cloned (flights-mcp source must be SCPable from here)
#
# Note on docker-compose.unified.yml: the file references
# /etc/proxy-server/agent_ssh_key as a compose secret. Docker Compose v2
# refuses to start a stack if a referenced secret file is missing, even
# if no service actually reads it. On the orchestrator, run
# Task 7 step 2 (ssh-keygen) BEFORE `docker compose up`, or temporarily
# comment out the `secrets:` block in the compose file.

set -euo pipefail

: "${AGENT_HOST:?set AGENT_HOST to the agent VM's IP or hostname}"
: "${AGENT_SSH_KEY_PUB:?set AGENT_SSH_KEY_PUB to the public key file path}"
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY for the agent}"
: "${DUFFEL_API_KEY:?set DUFFEL_API_KEY for flights-mcp}"
: "${ORCHESTRATOR_PRIVATE_IP:?set ORCHESTRATOR_PRIVATE_IP for ufw rule}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH="ssh -o StrictHostKeyChecking=accept-new root@${AGENT_HOST}"

echo "==> [1/8] base packages + claude-agent user"
${SSH} bash -se <<EOF
set -euo pipefail
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ufw fail2ban unattended-upgrades curl jq rsync git build-essential \
  python3 python3-pip python3-venv \
  squid

# Node 20 from NodeSource
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

# Claude Code CLI (npm global)
npm install -g @anthropic-ai/claude-code

# claude-agent user, no sudo, no docker
id claude-agent >/dev/null 2>&1 || useradd -m -s /bin/bash -U claude-agent
mkdir -p /agent/work
chown -R claude-agent:claude-agent /agent
chmod 750 /agent /agent/work
EOF

echo "==> [2/8] SSH authorized_keys"
scp -o StrictHostKeyChecking=accept-new "${AGENT_SSH_KEY_PUB}" root@${AGENT_HOST}:/tmp/agent_pub.key
${SSH} bash -se <<'EOF'
set -euo pipefail
install -d -o claude-agent -g claude-agent -m 700 /home/claude-agent/.ssh
install -o claude-agent -g claude-agent -m 600 /tmp/agent_pub.key /home/claude-agent/.ssh/authorized_keys
rm -f /tmp/agent_pub.key
EOF

echo "==> [3/8] ufw — ingress 22/tcp from orchestrator only"
# IMPORTANT ORDERING NOTE:
# We configure ufw BEFORE locking down sshd. If the operator's bootstrap
# SSH is from a non-orchestrator IP (operator workstation), they could
# get locked out the moment ufw enables. Provision script supports an
# optional OPERATOR_BOOTSTRAP_IP env var to add a second temporary allow
# rule; remove it manually after the smoke checks pass.
${SSH} bash -se <<EOF
set -euo pipefail
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from ${ORCHESTRATOR_PRIVATE_IP} to any port 22 proto tcp
if [[ -n "${OPERATOR_BOOTSTRAP_IP:-}" ]]; then
  ufw allow from ${OPERATOR_BOOTSTRAP_IP} to any port 22 proto tcp comment "TEMP: operator bootstrap"
fi
ufw --force enable
EOF

echo "==> [4/8] sshd config — PasswordAuth no, PermitRootLogin no, AcceptEnv"
${SSH} bash -se <<'EOF'
set -euo pipefail
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
grep -q "^AcceptEnv AIUI_AGENT_EFFORT" /etc/ssh/sshd_config || \
  echo "AcceptEnv AIUI_AGENT_EFFORT" >> /etc/ssh/sshd_config
systemctl reload ssh
EOF

echo "==> [5/8] Squid FQDN-allowlist proxy on 127.0.0.1:3128"
${SSH} bash -se <<'EOF'
set -euo pipefail
cat >/etc/squid/squid.conf <<'CONF'
http_port 127.0.0.1:3128

acl allowed_hosts dstdomain \
  .anthropic.com .duffel.com \
  .npmjs.org .nodesource.com \
  .pypi.org .pythonhosted.org \
  .ubuntu.com

http_access allow allowed_hosts
http_access deny all

# Logging — rotated by /etc/logrotate.d/squid (Ubuntu default)
access_log /var/log/squid/access.log squid
CONF
systemctl enable --now squid
systemctl reload squid

# Force claude-agent's outbound HTTPS through Squid
cat >/home/claude-agent/.profile <<'CONF'
export HTTPS_PROXY=http://127.0.0.1:3128
export HTTP_PROXY=http://127.0.0.1:3128
export NO_PROXY=127.0.0.1,localhost
CONF
chown claude-agent:claude-agent /home/claude-agent/.profile

# Apt also through Squid
cat >/etc/apt/apt.conf.d/95proxy <<'CONF'
Acquire::http::Proxy "http://127.0.0.1:3128";
Acquire::https::Proxy "http://127.0.0.1:3128";
CONF

# iptables: drop direct outbound 443 for claude-agent uid
iptables -A OUTPUT -m owner --uid-owner claude-agent \
  -p tcp --dport 443 ! -d 127.0.0.1 -j DROP
EOF

echo "==> [6/8] secrets — /home/claude-agent/.env"
${SSH} bash -se <<EOF
set -euo pipefail
install -o claude-agent -g claude-agent -m 600 /dev/null /home/claude-agent/.env
cat >>/home/claude-agent/.env <<INNER
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
DUFFEL_API_KEY=${DUFFEL_API_KEY}
IO_GATEWAY_URL=http://172.22.0.1:8085
INNER
EOF

echo "==> [7/8] flights-mcp install + Claude Code MCP registration"
# SCP the package over (operator workstation has the repo)
scp -r "${REPO_ROOT}/mcp-servers/flights" root@${AGENT_HOST}:/tmp/flights-mcp
${SSH} bash -se <<'EOF'
set -euo pipefail
rm -rf /opt/flights-mcp
mv /tmp/flights-mcp /opt/flights-mcp
python3 -m venv /opt/flights-mcp/venv
/opt/flights-mcp/venv/bin/pip install -e /opt/flights-mcp >/dev/null

# Register MCP server (user scope for claude-agent)
sudo -u claude-agent bash -c '
  source ~/.env
  claude mcp add --scope user flights \
    /opt/flights-mcp/venv/bin/python -m flights_mcp \
    --env "DUFFEL_API_KEY=$DUFFEL_API_KEY"
'
EOF

echo "==> [7b/8] io-mcp-wrappers install + register each wrapper"
# Use rsync with excludes to avoid copying the operator's local .venv,
# pip egg-info, and __pycache__ to the agent — those would either break
# `pip install -e` (wrong venv path picked up) or just bloat the transfer.
rsync -az --delete \
  --exclude='.venv' \
  --exclude='*.egg-info' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  "${REPO_ROOT}/mcp-servers/io-mcp-wrappers/" \
  root@${AGENT_HOST}:/tmp/io-mcp-wrappers/
${SSH} bash -se <<'EOF'
set -euo pipefail
rm -rf /opt/io-mcp
mv /tmp/io-mcp-wrappers /opt/io-mcp
python3 -m venv /opt/io-mcp/venv
/opt/io-mcp/venv/bin/pip install -e /opt/io-mcp >/dev/null

# Append IO_GATEWAY_URL to claude-agent's .profile (idempotent)
grep -q 'IO_GATEWAY_URL' /home/claude-agent/.profile || \
  echo 'export IO_GATEWAY_URL=http://172.22.0.1:8085' >> /home/claude-agent/.profile
chown claude-agent:claude-agent /home/claude-agent/.profile

# Allow ssh to pass IO_USER_JWT to the agent shell (idempotent)
grep -q '^AcceptEnv .*IO_USER_JWT' /etc/ssh/sshd_config || \
  sed -i 's/^AcceptEnv AIUI_AGENT_EFFORT$/AcceptEnv AIUI_AGENT_EFFORT IO_USER_JWT/' /etc/ssh/sshd_config
systemctl reload ssh

# Register each wrapper for claude-agent (user scope, idempotent —
# claude mcp add is idempotent on identical config).
# IO_GATEWAY_URL is static so we bake it into the env block here;
# IO_USER_JWT is dynamic (per-build) and is injected by the orchestrator
# via SSH SendEnv — Claude Code inherits it into MCP subprocesses
# automatically (Claude Code spreads process.env into each MCP spawn).
sudo -u claude-agent bash -c '
  source ~/.env
  for svc in web_search gdrive gmail calendar meetings meeting_kb dashboard excel_creator; do
    name="io-${svc//_/-}"
    claude mcp add --scope user "$name" \
      -e IO_GATEWAY_URL=http://172.22.0.1:8085 -- \
      /opt/io-mcp/venv/bin/python -m "io_mcp_$svc" || true
  done
'
EOF

echo "==> [8/8] workspace GC cron"
${SSH} bash -se <<'EOF'
set -euo pipefail
cat >/etc/cron.d/agent-work-gc <<'CONF'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
30 3 * * * claude-agent find /agent/work -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
CONF
chmod 644 /etc/cron.d/agent-work-gc
EOF

echo "OK — provisioning complete. Run scripts/smoke_agent_vm.sh next."
