# Deploy Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ad-hoc `scp file root@host:...` deploys with one bulletproof script that tracks deployed-SHA on the server, rsyncs only the changed files, rebuilds only the changed services, smokes them, and refuses partial deploys.

**Architecture:** Single bash script `scripts/deploy_orchestrator.sh` run from the operator workstation. State stored on the server in `/root/proxy-server/.deploy-state`. Adds `/healthz` endpoints to two services for the post-deploy smoke. No CI integration in v1.

**Tech Stack:** bash, rsync, ssh, curl, jq, docker compose. FastAPI for the two new `/healthz` routes.

**Spec:** `docs/superpowers/specs/2026-05-18-deploy-hygiene-design.md`

---

### Task 1: Add `/healthz` to tasks service

**Files:**
- Modify: `mcp-servers/tasks/main.py`
- Test: `mcp-servers/tasks/tests/test_healthz.py` (new)

- [ ] **Step 1: Write failing test**

Create `mcp-servers/tasks/tests/test_healthz.py`:

```python
from fastapi.testclient import TestClient
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_healthz_ok():
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
    from main import app
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && pytest tests/test_healthz.py -v`
Expected: 404 from the client → test fails (route not defined).

- [ ] **Step 3: Add the route to main.py**

In `mcp-servers/tasks/main.py`, after the `app = FastAPI(...)` line and the `app.include_router(...)` calls, add:

```python
@app.get("/healthz")
def healthz():
    """Liveness probe — no DB roundtrip. Used by deploy_orchestrator.sh."""
    return {"status": "ok"}
```

- [ ] **Step 4: Run test, expect pass**

Run: `cd mcp-servers/tasks && pytest tests/test_healthz.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_healthz.py
git commit -m "feat(tasks): add /healthz liveness endpoint for deploy smoke"
```

---

### Task 2: Add `/healthz` to api-gateway

**Files:**
- Modify: `api-gateway/main.py`
- Test: `api-gateway/tests/test_healthz.py` (create if `tests/` dir doesn't exist)

- [ ] **Step 1: Check if api-gateway has a tests dir**

Run: `ls api-gateway/tests/ 2>/dev/null || echo "no tests dir"`. If no dir, create `api-gateway/tests/__init__.py` (empty file) first.

- [ ] **Step 2: Write failing test**

Create `api-gateway/tests/test_healthz.py`:

```python
from fastapi.testclient import TestClient
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_healthz_ok():
    from main import app
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
```

- [ ] **Step 3: Verify it fails**

Run: `cd api-gateway && pytest tests/test_healthz.py -v` → 404 → fails.

(If api-gateway's `main.py` has heavy import side-effects requiring env vars, this test will need env stubs. Set them before the `from main import app`. Check `api-gateway/main.py` lines 1-30 for required env first; common candidates: `JWT_SECRET`, upstream URLs.)

- [ ] **Step 4: Add the route**

In `api-gateway/main.py`, add (near top of routes, before `proxy_handler`):

```python
@app.get("/healthz")
def healthz():
    """Liveness probe — no upstream call. Used by deploy_orchestrator.sh."""
    return {"status": "ok"}
```

If the gateway uses `proxy_handler` as a catch-all that intercepts every path, ensure `/healthz` is registered BEFORE the catch-all so it wins routing precedence.

- [ ] **Step 5: Verify pass + commit**

Run: `cd api-gateway && pytest tests/test_healthz.py -v` → PASS.

```
git add api-gateway/main.py api-gateway/tests/test_healthz.py api-gateway/tests/__init__.py
git commit -m "feat(api-gateway): add /healthz liveness endpoint for deploy smoke"
```

---

### Task 3: Create `scripts/deploy_orchestrator.sh` — skeleton + pre-flight

**Files:**
- Create: `scripts/deploy_orchestrator.sh`

- [ ] **Step 1: Create the script with shebang, opts, env-var checks**

```bash
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
```

- [ ] **Step 2: chmod +x and verify it parses**

```
chmod +x scripts/deploy_orchestrator.sh
bash -n scripts/deploy_orchestrator.sh
```

Expected: no syntax errors.

- [ ] **Step 3: Commit**

```
git add scripts/deploy_orchestrator.sh
git commit -m "feat(deploy): skeleton + pre-flight for deploy_orchestrator.sh"
```

---

### Task 4: Compute changed paths + map to services

**Files:**
- Modify: `scripts/deploy_orchestrator.sh`

- [ ] **Step 1: Append the path-computation block**

After the pre-flight block, append:

```bash
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
```

- [ ] **Step 2: Verify parse**

`bash -n scripts/deploy_orchestrator.sh` → no errors.

- [ ] **Step 3: Commit**

```
git add scripts/deploy_orchestrator.sh
git commit -m "feat(deploy): compute changed paths + map to docker compose services"
```

---

### Task 5: Rsync + rebuild + smoke + record SHA

**Files:**
- Modify: `scripts/deploy_orchestrator.sh`

- [ ] **Step 1: Append the rsync + rebuild block**

```bash
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
```

- [ ] **Step 2: Append the smoke block**

```bash
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
```

- [ ] **Step 3: Verify parse**

`bash -n scripts/deploy_orchestrator.sh` → no errors.

- [ ] **Step 4: Commit**

```
git add scripts/deploy_orchestrator.sh
git commit -m "feat(deploy): rsync + rebuild + smoke + .deploy-state recording"
```

---

### Task 6: Document + register the script

**Files:**
- Modify: `docs/agent-vm/README.md` (or create `docs/deploy/README.md`)

- [ ] **Step 1: Add a "Deploying orchestrator changes" section**

Append to `docs/agent-vm/README.md`:

```markdown
## Deploying orchestrator changes (added 2026-05-18)

Use `scripts/deploy_orchestrator.sh` instead of manual `scp`. It:
- Refuses dirty working trees (override with `--allow-dirty`)
- Tracks deployed-SHA in `/root/proxy-server/.deploy-state` on the server
- Rsyncs only files changed since last deploy
- Rebuilds only the docker compose services whose code touched
- Smokes via `/healthz` and exits non-zero on failure (and DOES NOT update `.deploy-state` on failure)

Usage:
\`\`\`bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
# First time:
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh --first-deploy
\`\`\`

If `.deploy-state` gets corrupted or you need to force a full re-deploy:
\`\`\`bash
ssh root@46.224.193.25 rm /root/proxy-server/.deploy-state
./scripts/deploy_orchestrator.sh --first-deploy
\`\`\`
```

- [ ] **Step 2: Commit**

```
git add docs/agent-vm/README.md
git commit -m "docs(deploy): operator guide for deploy_orchestrator.sh"
```

---

### Task 7: Live e2e — deploy this PR's tip with the new script

> The "no red marks remain" verification.

- [ ] **Step 1: First-time deploy**

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh --first-deploy
```

Expected: exits 0, prints `OK — deployed <sha>`, and `.deploy-state` written.

- [ ] **Step 2: Confirm smoke**

```bash
ssh root@46.224.193.25 'cat /root/proxy-server/.deploy-state | jq .'
curl -fsS http://46.224.193.25/healthz
curl -fsS http://46.224.193.25/tasks/healthz
```

Expected: SHA matches HEAD, both healthz endpoints return `{"status":"ok"}`.

- [ ] **Step 3: Re-run to confirm idempotency**

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

Expected: `Nothing to deploy — already at <sha>` and exits 0.

- [ ] **Step 4: MCP smoke still works**

```bash
ORCH_HOST=46.224.193.25 IO_USER_JWT=<jwt> ./scripts/smoke_mcp_access.sh
```

Expected: full e2e still passes (proves the deploy mechanism didn't break existing functionality).
