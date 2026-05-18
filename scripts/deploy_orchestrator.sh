#!/usr/bin/env bash
# Deploy orchestrator changes to Hetzner via rsync.
#
# Refuses to deploy if working tree is dirty (unless --allow-dirty).
# Tracks last-deployed SHA in /root/proxy-server/.deploy-state on the server.
# Rebuilds only changed docker compose services.
# Smokes them via /healthz before recording the new SHA.
#
# Usage:
#   ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh [--allow-dirty] [--first-deploy]
set -euo pipefail

: "${ORCH_HOST:?set ORCH_HOST to the orchestrator IP/hostname}"
ORCH_USER="${ORCH_USER:-root}"
ORCH_PATH="${ORCH_PATH:-/root/proxy-server}"

ALLOW_DIRTY=0
FIRST_DEPLOY=0
for arg in "$@"; do
  case "$arg" in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    --first-deploy) FIRST_DEPLOY=1 ;;
    *) echo "unknown arg: $arg"; exit 1 ;;
  esac
done

SSH="ssh -o StrictHostKeyChecking=accept-new ${ORCH_USER}@${ORCH_HOST}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

echo "==> [1/6] pre-flight"

if [[ "${ALLOW_DIRTY}" -eq 0 ]]; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: working tree has uncommitted changes. Commit or pass --allow-dirty."
    exit 1
  fi
fi

CURRENT_SHA="$(git rev-parse HEAD)"
echo "  current commit: ${CURRENT_SHA}"

PREVIOUS_SHA=""
if ${SSH} "test -f ${ORCH_PATH}/.deploy-state"; then
  PREVIOUS_SHA="$(${SSH} "cat ${ORCH_PATH}/.deploy-state" | jq -r .sha)"
  echo "  last deployed: ${PREVIOUS_SHA}"
elif [[ "${FIRST_DEPLOY}" -ne 1 ]]; then
  echo "ERROR: no .deploy-state on server. Re-run with --first-deploy if this is intentional."
  exit 1
else
  echo "  first deploy — no previous SHA"
fi

if [[ "${PREVIOUS_SHA}" == "${CURRENT_SHA}" ]]; then
  echo "Nothing to deploy — already at ${CURRENT_SHA}"
  exit 0
fi
