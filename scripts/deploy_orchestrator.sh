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

echo "==> [2/6] compute changed paths"

ORCH_PATH_PATTERN='^(mcp-servers/|api-gateway/|Caddyfile$|docker-compose\.unified\.yml$|scripts/)'

if [[ -z "${PREVIOUS_SHA}" ]]; then
  # First deploy — everything is "changed"
  CHANGED=$(git ls-files | grep -E "${ORCH_PATH_PATTERN}" || true)
else
  CHANGED=$(git diff --name-only "${PREVIOUS_SHA}..${CURRENT_SHA}" | grep -E "${ORCH_PATH_PATTERN}" || true)
fi

if [[ -z "${CHANGED}" ]]; then
  echo "  no orchestrator-relevant files changed"
  # Record SHA bump anyway so next run is fast — but mention nothing rebuilt
  ${SSH} "echo '{\"sha\":\"${CURRENT_SHA}\",\"deployed_at\":\"$(date -Iseconds)\",\"deployed_by\":\"${USER}@$(hostname)\",\"nothing_rebuilt\":true}' > ${ORCH_PATH}/.deploy-state"
  echo "OK — SHA recorded, nothing rebuilt"
  exit 0
fi

echo "  changed paths:"
echo "${CHANGED}" | sed 's/^/    /'

echo "==> [3/6] map paths to services"

declare -A SERVICES=()
while IFS= read -r path; do
  case "${path}" in
    mcp-servers/tasks/*)         SERVICES[tasks]=1 ;;
    mcp-servers/web-search/*)    SERVICES[mcp-web-search]=1 ;;
    mcp-servers/gmail/*)         SERVICES[mcp-gmail]=1 ;;
    mcp-servers/gdrive/*)        SERVICES[mcp-gdrive]=1 ;;
    mcp-servers/calendar/*)      SERVICES[mcp-calendar]=1 ;;
    mcp-servers/meetings/*)      SERVICES[mcp-meetings]=1 ;;
    mcp-servers/meeting-kb/*)    SERVICES[mcp-meeting-kb]=1 ;;
    mcp-servers/dashboard/*)     SERVICES[mcp-dashboard]=1 ;;
    mcp-servers/excel-creator/*) SERVICES[mcp-excel-creator]=1 ;;
    mcp-servers/io-mcp-wrappers/*) ;;  # agent-side only, not a compose service
    api-gateway/*)               SERVICES[api-gateway]=1 ;;
    Caddyfile)                   SERVICES[caddy]=1 ;;
    docker-compose.unified.yml)  SERVICES[ALL]=1 ;;
    scripts/*)                   ;; # script changes don't trigger service rebuild
  esac
done <<< "${CHANGED}"

if [[ -n "${SERVICES[ALL]:-}" ]]; then
  echo "  docker-compose.unified.yml changed — will rebuild ALL services"
  REBUILD_LIST="ALL"
else
  REBUILD_LIST="${!SERVICES[*]}"
  echo "  will rebuild: ${REBUILD_LIST:-(none)}"
fi
