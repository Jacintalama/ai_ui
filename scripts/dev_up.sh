#!/usr/bin/env bash
# Local Docker stack: one command up, down, reset or logs.
#
#   bash scripts/dev_up.sh up            # start (or rebuild), seed, then check
#   bash scripts/dev_up.sh down          # stop; data is kept
#   bash scripts/dev_up.sh reset         # stop and delete the aiui-dev volumes
#   bash scripts/dev_up.sh logs <svc>    # follow one service's logs
#
# Run from Git Bash. Always passes --env-file .env.dev: without it compose
# would read the production-shaped .env in the repo root.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

ENV_FILE=".env.dev"
COMPOSE_FILE="docker-compose.dev.yml"
PROJECT="aiui-dev"
BASE_URL="http://localhost:8090"
WORKSPACE="dev/workspace"

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

# Docker Desktop may be stopped. Start it and wait for the engine.
ensure_docker() {
    if docker info >/dev/null 2>&1; then
        return 0
    fi
    echo "Docker is not running; starting Docker Desktop"
    local exe="/c/Program Files/Docker/Docker/Docker Desktop.exe"
    if [ ! -f "$exe" ]; then
        echo "Docker Desktop not found at $exe" >&2
        exit 1
    fi
    "$exe" >/dev/null 2>&1 &
    local i
    for i in $(seq 1 90); do
        if docker info >/dev/null 2>&1; then
            echo "Docker is up"
            return 0
        fi
        sleep 2
    done
    echo "Docker did not come up within 180 s" >&2
    exit 1
}

# The App Builder's workspace. tasks mounts this at /workspace/ai_ui instead
# of the repo, so a local build commits here and never into this checkout.
ensure_workspace() {
    mkdir -p "$WORKSPACE/apps"
    if [ ! -d "$WORKSPACE/.git" ]; then
        git -C "$WORKSPACE" init -q
        # An empty first commit, so HEAD exists: the regression baseline and
        # the version history both read it.
        touch "$WORKSPACE/apps/.gitkeep"
        git -C "$WORKSPACE" add apps/.gitkeep
        git -C "$WORKSPACE" -c user.name="aiui-dev" -c user.email="dev@local.test" \
            commit -q -m "Local dev workspace"
        echo "made $WORKSPACE (its own git repo)"
    fi
    # The repo's default identity. app_git.sweep_app_commit commits with no
    # -c user.* when a task has no assignee, and the tasks container has no
    # global git identity, so without this every such commit failed with
    # "Author identity unknown" (seen 2026-10-12). Set on every up, so a
    # workspace made before this line gets it too.
    git -C "$WORKSPACE" config user.name "aiui-dev"
    git -C "$WORKSPACE" config user.email "dev@local.test"
}

# Wait until a URL answers 200, or fail after $2 seconds.
wait_for() {
    local url="$1" limit="$2" waited=0
    until [ "$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)" = "200" ]; do
        if [ "$waited" -ge "$limit" ]; then
            echo "timed out after ${limit}s waiting for $url" >&2
            return 1
        fi
        sleep 3
        waited=$((waited + 3))
    done
    echo "ready after ${waited}s: $url"
}

cmd_up() {
    ensure_docker
    python scripts/dev_env.py
    ensure_workspace
    compose up -d --build
    # Open WebUI's first boot runs its migrations and can take minutes.
    wait_for "$BASE_URL/tasks/healthz" 300
    # Not /health: Caddy answers that itself. /api/config needs Open WebUI.
    wait_for "$BASE_URL/api/config" 600
    python scripts/dev_seed.py
    python scripts/dev_check.py
}

cmd_down() {
    compose down
}

cmd_reset() {
    echo "This deletes the $PROJECT volumes (its database and Open WebUI data)."
    echo "Production is not touched. dev/workspace is kept."
    read -r -p "Type reset to continue: " answer
    if [ "$answer" != "reset" ]; then
        echo "cancelled"
        exit 1
    fi
    # down -v removes only the volumes this compose project declares, and
    # every one of them is named $PROJECT_<name>.
    compose down -v
}

cmd_logs() {
    if [ $# -lt 1 ]; then
        echo "usage: $0 logs <service>" >&2
        exit 2
    fi
    compose logs -f --tail 200 "$1"
}

case "${1:-}" in
    up) cmd_up ;;
    down) cmd_down ;;
    reset) cmd_reset ;;
    logs) shift; cmd_logs "$@" ;;
    *)
        echo "usage: $0 up|down|reset|logs <service>" >&2
        exit 2
        ;;
esac
