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
  # Parse ON THE SERVER (its python3 always exists). Workstation-side parsing
  # broke on Windows Git Bash where python3 is absent: the pipe swallowed the
  # JSON and the local fallback read empty stdin, aborting pre-flight.
  PREVIOUS_SHA="$(${SSH} "python3 -c \"import json;print(json.load(open('${ORCH_PATH}/.deploy-state'))['sha'])\"")"
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

# mcp-proxy/ joined this on 2026-11-09. It is a TOP LEVEL directory, so
# nothing in it had ever deployed itself: PRs #139, #142, #149 and #150 all
# shipped by hand and its image was three days old when that was noticed.
# Hand-shipping is also what blocks the sweep below, so the two were one bug.
ORCH_PATH_PATTERN='^(mcp-servers/|mcp-proxy/|api-gateway/|Caddyfile$|docker-compose\.unified\.yml$|scripts/)'

if [[ -z "${PREVIOUS_SHA}" ]]; then
  # First deploy — everything is "changed"
  CHANGED=$(git ls-files | grep -E "${ORCH_PATH_PATTERN}" || true)
else
  # --diff-filter=d EXCLUDES deletions (lowercase excludes, uppercase
  # selects). This list is handed to rsync as files to SEND, so a path the
  # commit deleted makes rsync exit 23 and takes the whole deploy with it:
  #
  #   rsync: [sender] link_stat ".../test_tasks_launcher.py" failed:
  #          No such file or directory (2)
  #
  # That happened on 2026-11-06 and three deploys in a row failed on one
  # deleted test file, while the merges looked fine from GitHub.
  CHANGED=$(git diff --name-only --diff-filter=d "${PREVIOUS_SHA}..${CURRENT_SHA}" | grep -E "${ORCH_PATH_PATTERN}" || true)
  # Deletions are REPORTED rather than copied. Nothing here removes them
  # from the server, so the file lives on, and a stale module nobody
  # mentioned is how a container keeps running code that left the repo.
  DELETED=$(git diff --name-only --diff-filter=D "${PREVIOUS_SHA}..${CURRENT_SHA}" | grep -E "${ORCH_PATH_PATTERN}" || true)
fi

# Files that are NEVER deployed from the repo. The server's templates.py is
# ahead of the repo's (more App Builder templates, CLAUDE.md "Hard rules"), so
# carrying the repo's copy would silently drop templates. ORCH_DEPLOY_TEMPLATES=1
# overrides, for the one deploy that is meant to replace it.
if [[ "${ORCH_DEPLOY_TEMPLATES:-0}" -ne 1 ]]; then
  CHANGED=$(echo "${CHANGED}" | grep -v -E '^mcp-servers/tasks/templates\.py$' || true)
fi

if [[ -z "${CHANGED}" ]]; then
  echo "  no orchestrator-relevant files changed"
  # Record SHA bump anyway so next run is fast — but mention nothing rebuilt
  ${SSH} "echo '{\"sha\":\"${CURRENT_SHA}\",\"deployed_at\":\"$(date -Iseconds)\",\"deployed_by\":\"${USER:-${USERNAME:-unknown}}@$(hostname)\",\"nothing_rebuilt\":true}' > ${ORCH_PATH}/.deploy-state"
  echo "OK — SHA recorded, nothing rebuilt"
  exit 0
fi

echo "  changed paths:"
echo "${CHANGED}" | sed 's/^/    /'

if [[ -n "${DELETED:-}" ]]; then
  echo "  DELETED in the repo and LEFT ON THE SERVER:"
  echo "${DELETED}" | sed 's/^/    /'
  echo "    (not copied and not removed. Delete by hand if a stale one"
  echo "     would be imported or served.)"
fi

echo "==> [2b] server-edit sweep"

# Teammates edit files directly on the box, and the server's git tree makes
# its own snapshot commits (CLAUDE.md, "Server realities"). A repo-wins rsync
# over such a file silently reverts their work. So before anything is sent,
# every changed file on the server is compared with the version the LAST
# deploy sent (git show PREVIOUS_SHA:path), CRLF-normalised. A file that
# differs was edited on the box: the deploy stops and names it, unless
# ORCH_OVERWRITE_SERVER_EDITS=1 says the repo is meant to win.
if [[ -n "${PREVIOUS_SHA}" && "${ORCH_OVERWRITE_SERVER_EDITS:-0}" -ne 1 ]]; then
  EDITED_ON_SERVER=""
  while IFS= read -r path; do
    [[ -z "${path}" ]] && continue
    # Not deployed before: nothing on the box to protect.
    if ! git cat-file -e "${PREVIOUS_SHA}:${path}" 2>/dev/null; then continue; fi
    want="$(git show "${PREVIOUS_SHA}:${path}" | tr -d '\r' | sha256sum | cut -d' ' -f1)"
    have="$(${SSH} "test -f '${ORCH_PATH}/${path}' && tr -d '\r' < '${ORCH_PATH}/${path}' | sha256sum | cut -d' ' -f1 || echo missing")"
    # Already holding the version this deploy would WRITE, so the rsync is
    # a no-op for it and there is nothing to lose: you cannot destroy
    # somebody's work by writing bytes that are already there.
    #
    # That is exactly what a file deployed BY HAND looks like. When a
    # deploy fails I ship the merged file myself, so the box ends up with
    # the repo's newer version while .deploy-state still names the old
    # commit; the sweep then reads it as an edit on the box and refuses, so
    # ONE failure blocks every later deploy until a person intervenes.
    # Measured 2026-11-09: three days with nothing deployed, eight runs and
    # no success, and a hash sweep of all 1208 watched files found 3
    # differing, every one the repo being ahead, no teammate edit anywhere.
    #
    # This weakens nothing. A teammate's own edit does not coincidentally
    # equal the repo's new version, so the comparison below still catches
    # it.
    want_now="$(git show "${CURRENT_SHA}:${path}" | tr -d '\r' | sha256sum | cut -d' ' -f1)"
    if [[ "${have}" == "${want_now}" ]]; then continue; fi
    if [[ "${have}" != "missing" && "${have}" != "${want}" ]]; then
      EDITED_ON_SERVER+="    ${path}"$'\n'
    fi
  done <<< "${CHANGED}"
  if [[ -n "${EDITED_ON_SERVER}" ]]; then
    echo "ERROR: these files were changed on the server since the last deploy;"
    echo "       deploying would overwrite that work:"
    printf '%s' "${EDITED_ON_SERVER}"
    echo "       Pull the server's version into the repo first, or re-run with"
    echo "       ORCH_OVERWRITE_SERVER_EDITS=1 if the repo is meant to win."
    exit 3
  fi
  echo "  ok: nothing changed on the server behind the last deploy"
fi

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
    mcp-proxy/*)                 SERVICES[mcp-proxy]=1 ;;
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

# --inplace, because one of the files under mcp-servers/ is BIND-MOUNTED
# into another container as a single file: mcp-servers/gdrive/
# integrations-ui.js, mounted at /app/build/static/integrations-ui.js in
# open-webui. rsync's default is to write a temporary file and rename it
# over the target, which gives the path a NEW INODE. A single-file bind
# mount follows the inode, so the container keeps serving the old file and
# the page silently stays on yesterday's code until somebody restarts it.
#
# That is why that file had always been placed by hand with `cat >`, and
# why every change to it sat outside this pipeline. --inplace writes
# through the existing inode, so it does not have to.
#
# The cost is that an interrupted transfer leaves a half-written file
# rather than the old one. For source a service is rebuilt from, a failed
# build is louder than a stale page.
rsync -avz --relative --inplace \
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
      if [[ "${svc}" == "tasks" ]]; then
        # mcp-proxy caches each backing server's OpenAPI in TOOLS_CACHE
        # when IT boots, and never re-reads a server rebuilt underneath
        # it. The whole my-* family, 210 tools, is served by `tasks`, so
        # without this a tool's new shape never reaches a model.
        #
        # Measured 2026-11-09: PR #159 changed ClickUp's `assignees` from
        # a string to an array, the deploy went green, the container had
        # the new definition, and mcp-proxy still told every model
        # "string". A correct container, a green deploy, and a fix that
        # did nothing.
        #
        # A restart, not a rebuild: mcp-proxy's own image has not
        # changed, and rebuilding it on every tasks deploy would add
        # minutes to every deploy for nothing.
        echo "  tasks was rebuilt, so mcp-proxy must re-read its tools"
        ${SSH} "cd ${ORCH_PATH} && docker compose -f docker-compose.unified.yml restart mcp-proxy"
      fi
    fi
  done
fi

echo "==> [6/6] post-deploy smoke"

SMOKE_FAIL=0

# How long a just-restarted service is given to start answering. 20 tries of
# 3 seconds is a minute, which is far more than tasks needs and still fails
# in reasonable time when something is genuinely broken.
SMOKE_TRIES="${SMOKE_TRIES:-20}"
SMOKE_WAIT="${SMOKE_WAIT:-3}"

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
  # Asked repeatedly, not once. A service that has just been recreated is
  # not listening yet, and a single curl here returns 502 and calls a deploy
  # that worked a failure. Measured 2026-11-03: tasks built, restarted, and
  # answered 200 moments later, while the run was marked failed and
  # .deploy-state was left stale, so the NEXT deploy recomputed its changed
  # paths from the wrong commit.
  #
  # A deploy that lies about its outcome is worse than one that fails: it
  # trains everybody to ignore the result.
  ok=0
  for attempt in $(seq 1 "${SMOKE_TRIES}"); do
    if curl -fsS -o /dev/null -m 10 "${url}"; then
      ok=1
      [[ "${attempt}" -gt 1 ]] && echo "  ok: ${svc} after ${attempt} tries"
      break
    fi
    sleep "${SMOKE_WAIT}"
  done
  if [[ "${ok}" -eq 1 ]]; then
    echo "  ok: ${svc} -> ${url}"
  else
    echo "  FAIL: ${svc} -> ${url} never answered after $(( SMOKE_TRIES * SMOKE_WAIT ))s"
    SMOKE_FAIL=1
  fi
done

if [[ "${SMOKE_FAIL}" -eq 1 ]]; then
  echo "DEPLOY SMOKE FAILED — .deploy-state NOT updated. Server may be in inconsistent state."
  echo "Investigate logs: ssh ${ORCH_USER}@${ORCH_HOST} 'docker compose -f ${ORCH_PATH}/docker-compose.unified.yml logs --tail=100'"
  exit 2
fi

echo "==> recording .deploy-state"
${SSH} "echo '{\"sha\":\"${CURRENT_SHA}\",\"deployed_at\":\"$(date -Iseconds)\",\"deployed_by\":\"${USER:-${USERNAME:-unknown}}@$(hostname)\"}' > ${ORCH_PATH}/.deploy-state"

echo ""
echo "OK — deployed ${CURRENT_SHA}"
