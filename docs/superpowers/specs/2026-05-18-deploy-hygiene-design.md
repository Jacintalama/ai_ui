# Deploy Hygiene — Design

**Date:** 2026-05-18
**Branch:** `feat/vm-agent-flight-mcp`
**Status:** Approved

## Problem

The orchestrator (Hetzner VPS at `46.224.193.25`) is deployed by hand: operator SCPs individual files to `/root/proxy-server/`, then SSH's in to run `docker compose -f docker-compose.unified.yml up -d --build <service>`. Memory note: *"No git on server — Deploy via SCP to /root/proxy-server/, then docker compose."*

Last week this bit us: `mcp-servers/tasks/routes_execution.py` had a JWT-extraction commit landed in git, but the file was never SCP'd alongside `remote_executor.py`. The orchestrator silently ran the old code → user JWT was never forwarded to the agent VM → all MCP wrappers failed auth with `default@local`. Took 90 minutes to diagnose during the e2e smoke.

Class of bug: **partial deploys go undetected** because there's no manifest of "what should be deployed" vs. "what is deployed."

## Goal

A single command, runnable from the operator workstation, that:

1. Refuses to deploy if working tree is dirty (or has explicit `--allow-dirty` flag).
2. Computes which orchestrator files differ between the current git commit and the last successfully deployed commit.
3. Rsyncs only the changed orchestrator paths to the server.
4. Records the new deployed commit SHA on the server in `/root/proxy-server/.deploy-state` (a JSON file with `{"sha": "...", "deployed_at": "...", "deployed_by": "..."}`).
5. Rebuilds only the docker compose services whose files changed.
6. Runs a post-deploy smoke (HTTP healthcheck on each rebuilt service).
7. Exits non-zero with a clear error if any step fails — never silently partial.

Non-goals: blue-green deploys, automatic rollback, CI integration. Keeping v1 operator-driven.

## Design

### New file: `scripts/deploy_orchestrator.sh`

Bash script, ~150 lines, no Python dependency. Idempotent — re-run on same commit is a no-op (and exits 0 with "nothing to deploy"). Adopts the same shape as `provision_agent_vm.sh` for operator familiarity.

#### Env vars

```
ORCH_HOST=46.224.193.25     # required
ORCH_USER=root              # default root
ORCH_PATH=/root/proxy-server # default
```

#### Steps

```
[1/6] Pre-flight
  - require ORCH_HOST set
  - run `git diff --quiet && git diff --cached --quiet`
    → if fails AND --allow-dirty not passed, abort
  - read current commit SHA
  - read remote .deploy-state via ssh → previous_sha (or empty if first deploy)
  - if previous_sha == current_sha: echo "nothing to deploy"; exit 0

[2/6] Compute changed paths
  - if previous_sha empty: changed_paths = ALL orchestrator paths (initial deploy)
  - else: changed_paths = `git diff --name-only $previous_sha..HEAD | grep -E '^(mcp-servers/|api-gateway/|Caddyfile|docker-compose\.unified\.yml|scripts/)'`
  - echo summary: "Deploying $(echo $changed_paths | wc -w) file(s) since $previous_sha"

[3/6] Map paths → docker compose services
  - mcp-servers/tasks/* → tasks
  - mcp-servers/web-search/* → mcp-web-search
  - mcp-servers/gmail/* → mcp-gmail
  - … one mapping per service ...
  - api-gateway/* → api-gateway
  - Caddyfile → caddy (restart not rebuild)
  - docker-compose.unified.yml → ALL (since structure may have changed)

[4/6] Rsync changed files
  - rsync -avz --relative changed_paths $ORCH_USER@$ORCH_HOST:$ORCH_PATH/
  - --relative preserves directory structure
  - exclude: __pycache__, .pytest_cache, *.pyc, .venv, *.egg-info

[5/6] Rebuild + restart services
  - ssh into server
  - for svc in $rebuild_services: docker compose -f docker-compose.unified.yml up -d --build $svc
  - if Caddyfile changed: docker compose exec caddy caddy reload

[6/6] Post-deploy smoke
  - for each rebuilt service, hit its healthcheck endpoint via the API Gateway
  - tasks → curl http://$ORCH_HOST/tasks/healthz → expect 200
  - api-gateway → curl http://$ORCH_HOST/healthz → expect 200
  - mcp-* → curl http://$ORCH_HOST/<svc>/healthz → expect 200 OR 404 OK (some
    backends don't expose /healthz; in that case fall back to "container is
    `Up` per docker ps")
  - if any fail: echo "DEPLOY SMOKE FAILED" and exit 2 — but do NOT roll back
    automatically (operator decides whether to revert or fix forward)

[7/6] Write .deploy-state
  - ONLY if step 6 succeeded
  - ssh server: write {"sha":"<current_sha>","deployed_at":"<iso>","deployed_by":"$USER@$(hostname)"} to /root/proxy-server/.deploy-state

echo "OK — deployed $current_sha"
```

#### Pre-flight error messages

```
ERROR: working tree has uncommitted changes. Commit or use --allow-dirty.
ERROR: cannot read .deploy-state from $ORCH_HOST — is this the first deploy? Re-run with --first-deploy.
ERROR: post-deploy smoke failed for service 'tasks' — see logs above. Server is in inconsistent state.
```

### Healthcheck additions

`mcp-servers/tasks/main.py` already has a default `/` route. Add `/healthz` returning `{"status": "ok"}` with no DB roundtrip (fast). Same for `api-gateway/main.py`. Other MCP backends already have one or fall back to docker ps check.

### Test plan

1. **Dry run on a clean tree, same SHA as deployed:** must exit 0 with "nothing to deploy."
2. **Dry run on a clean tree, one orchestrator file ahead:** must rsync only that one file + rebuild only its mapped service.
3. **Dirty tree without `--allow-dirty`:** must abort with non-zero, no files transferred.
4. **Simulate post-deploy smoke failure:** manually break a service, re-deploy, confirm script exits 2 and `.deploy-state` is NOT updated.
5. **Live first-time use:** deploy current branch state to Hetzner, confirm tasks service still serves, MCP smoke still passes.

### Risks

- **Caddy reload not enough for some changes** — if Caddyfile adds a new upstream block, reload may fail to pick up new upstreams. Mitigation: if Caddyfile changes, do `docker compose restart caddy` not just reload. Trade off ~1s downtime for correctness.
- **--relative requires gnu rsync 3.x** — Mac default rsync (2.6.9) lacks it. Operator workstation must have a modern rsync (already required by `provision_agent_vm.sh`).
- **First deploy bootstrap** — `.deploy-state` doesn't exist yet on Hetzner. Script must handle this and either prompt for confirmation or take `--first-deploy` flag.

## Files changed

- `scripts/deploy_orchestrator.sh` — new (~150 lines)
- `mcp-servers/tasks/main.py` — add `/healthz`
- `api-gateway/main.py` — add `/healthz`
- `docs/agent-vm/README.md` — add "Deploying orchestrator changes" section pointing at the new script

## Acceptance

- All 5 test-plan scenarios pass.
- One real-world deploy completes (from this PR's tip).
- `.deploy-state` correctly written on Hetzner with current SHA.
