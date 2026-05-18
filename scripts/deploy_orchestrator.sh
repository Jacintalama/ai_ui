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
  # Parse via python (universally available; avoids requiring jq on operator workstation)
  PREVIOUS_SHA="$(${SSH} "cat ${ORCH_PATH}/.deploy-state" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["sha"])' 2>/dev/null || python -c 'import json,sys;print(json.loads(sys.stdin.read())["sha"])')"
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

echo "==> [4/6] rsync changed files"

# Build rsync src list. Use --relative so dir structure is preserved server-side.
RSYNC_PATHS=()
while IFS= read -r path; do
  [[ -n "${path}" ]] && RSYNC_PATHS+=("${path}")
done <<< "${CHANGED}"

rsync -avz --relative \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='*.egg-info' \
  "${RSYNC_PATHS[@]}" \
  "${ORCH_USER}@${ORCH_HOST}:${ORCH_PATH}/"

echo "==> [5/6] rebuild + restart services"

if [[ "${REBUILD_LIST}" == "ALL" ]]; then
  ${SSH} "cd ${ORCH_PATH} && docker compose -f docker-compose.unified.yml up -d --build"
else
  for svc in ${REBUILD_LIST}; do
    if [[ "${svc}" == "caddy" ]]; then
      # Caddy: restart rather than reload — reload may miss new upstream blocks
      ${SSH} "cd ${ORCH_PATH} && docker compose -f docker-compose.unified.yml restart caddy"
    else
      ${SSH} "cd ${ORCH_PATH} && docker compose -f docker-compose.unified.yml up -d --build ${svc}"
    fi
  done
fi

echo "==> [6/6] post-deploy smoke"

SMOKE_FAIL=0

# Map services → smoke URL
declare -A SMOKE_URLS=(
  [tasks]="http://${ORCH_HOST}/tasks/healthz"
  [api-gateway]="http://${ORCH_HOST}/healthz"
  [caddy]="http://${ORCH_HOST}/healthz"
)

if [[ "${REBUILD_LIST}" == "ALL" ]]; then
  CHECK_LIST="tasks api-gateway caddy"
else
  CHECK_LIST="${REBUILD_LIST}"
fi

for svc in ${CHECK_LIST}; do
  url="${SMOKE_URLS[${svc}]:-}"
  if [[ -z "${url}" ]]; then
    # Service has no /healthz — check container is `Up` instead
    if ${SSH} "docker compose -f ${ORCH_PATH}/docker-compose.unified.yml ps ${svc} | grep -q 'Up'"; then
      echo "  ok: ${svc} (container Up)"
    else
      echo "  FAIL: ${svc} container is not Up"
      SMOKE_FAIL=1
    fi
    continue
  fi
  if curl -fsS -o /dev/null -m 10 "${url}"; then
    echo "  ok: ${svc} → ${url}"
  else
    echo "  FAIL: ${svc} → ${url} returned non-200"
    SMOKE_FAIL=1
  fi
done

if [[ "${SMOKE_FAIL}" -eq 1 ]]; then
  echo "DEPLOY SMOKE FAILED — .deploy-state NOT updated. Server may be in inconsistent state."
  echo "Investigate logs: ssh ${ORCH_USER}@${ORCH_HOST} 'docker compose -f ${ORCH_PATH}/docker-compose.unified.yml logs --tail=100'"
  exit 2
fi

echo "==> recording .deploy-state"
${SSH} "echo '{\"sha\":\"${CURRENT_SHA}\",\"deployed_at\":\"$(date -Iseconds)\",\"deployed_by\":\"${USER}@$(hostname)\"}' > ${ORCH_PATH}/.deploy-state"

echo ""
echo "OK — deployed ${CURRENT_SHA}"
