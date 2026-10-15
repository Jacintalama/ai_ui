#!/usr/bin/env bash
# Local Docker stack: one command up, down, reset or logs.
#
#   bash scripts/dev_up.sh up            # start (or rebuild), seed, then check
#   bash scripts/dev_up.sh down          # stop; data is kept
#   bash scripts/dev_up.sh reset         # stop and delete the aiui-dev volumes
#   bash scripts/dev_up.sh logs <svc>    # follow one service's logs
#   bash scripts/dev_up.sh model         # which model, and which compose files
#   bash scripts/dev_up.sh config [args] # docker compose config, as up sees it
#
# Run from Git Bash. Always passes --env-file .env.dev: without it compose
# would read the production-shaped .env in the repo root (and fail, since
# the dev compose files interpolate only DEV_ names). Always passes
# -p aiui-dev too: a COMPOSE_PROJECT_NAME in the shell beats the file's
# `name: aiui-dev`, and would put the stack under another project.
#
# LOCAL_MODEL in .env.dev picks the model: fake (dev/fake-llm, the default)
# or real (OpenRouter's free models, docker-compose.dev.real.yml on top).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# DEV_ENV_FILE is for checking the switch against a throwaway env file.
ENV_FILE="${DEV_ENV_FILE:-.env.dev}"
COMPOSE_FILE="docker-compose.dev.yml"
REAL_FILE="docker-compose.dev.real.yml"
PROJECT="aiui-dev"
BASE_URL="http://localhost:8090"
WORKSPACE="dev/workspace"
# The mode the stack was last brought up in (dev/ is gitignored here).
MODE_STAMP="dev/out/last-model"

# One value from the env file, CR stripped. Only ever used for LOCAL_MODEL
# and for testing whether the key is empty: never echo a secret.
env_value() {
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

local_model() {
    local mode
    mode="$(env_value LOCAL_MODEL)"
    echo "${mode:-fake}"
}

compose_files() {
    case "$(local_model)" in
        fake) echo "-f $COMPOSE_FILE" ;;
        real) echo "-f $COMPOSE_FILE -f $REAL_FILE" ;;
        *) echo "LOCAL_MODEL must be fake or real" >&2; exit 2 ;;
    esac
}

compose() {
    local files
    files="$(compose_files)"
    # $files is unquoted on purpose: it is two or four words.
    # shellcheck disable=SC2086
    docker compose -p "$PROJECT" --env-file "$ENV_FILE" $files "$@"
}

# Real mode needs a key, and a switch needs a fresh Open WebUI volume,
# because the connection saved in its database beats the env after first
# boot. Say so up front rather than let the seed time out on a model that
# is never listed.
check_model_switch() {
    local mode last
    mode="$(local_model)"
    if [ "$mode" = "real" ] && [ -z "$(env_value DEV_OPENROUTER_API_KEY)" ]; then
        echo "LOCAL_MODEL=real needs DEV_OPENROUTER_API_KEY in $ENV_FILE" >&2
        exit 1
    fi
    last="$(cat "$MODE_STAMP" 2>/dev/null | tr -d '\r' || true)"
    if [ -n "$last" ] && [ "$last" != "$mode" ]; then
        echo "WARNING: the stack last ran with LOCAL_MODEL=$last, now $mode."
        echo "Open WebUI keeps its saved connection, so run"
        echo "'bash scripts/dev_up.sh reset' first, or edit the connection"
        echo "under Admin > Settings > Connections."
    fi
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

# Create .env.dev, or migrate an old one to the DEV_ names in place (values
# kept). Prints key names only.
ensure_env() {
    python scripts/dev_env.py --path "$ENV_FILE"
}

# Open WebUI caches the fake model's address. When `up --build` recreates
# fake-llm it can come back on a new address while Open WebUI keeps dialling
# the old one, and every agent turn fails with "Server Connection Error"
# (seen 2026-10-15: "Connect call failed ('172.27.0.2', 9000)"). So when
# fake-llm started after Open WebUI, Open WebUI is restarted too.
refresh_model_route() {
    local owui llm
    owui="$(compose ps -q open-webui)"
    llm="$(compose ps -q fake-llm)"
    [ -n "$owui" ] && [ -n "$llm" ] || return 0
    owui="$(docker inspect -f '{{.State.StartedAt}}' "$owui")"
    llm="$(docker inspect -f '{{.State.StartedAt}}' "$llm")"
    if [[ "$llm" > "$owui" ]]; then
        echo "fake-llm was recreated after Open WebUI: restarting Open WebUI"
        compose restart open-webui
    fi
}

cmd_up() {
    ensure_docker
    ensure_env
    check_model_switch
    ensure_workspace
    compose up -d --build
    refresh_model_route
    mkdir -p "$(dirname "$MODE_STAMP")"
    local_model > "$MODE_STAMP"
    # Open WebUI's first boot runs its migrations and can take minutes.
    wait_for "$BASE_URL/tasks/healthz" 300
    # Not /health: Caddy answers that itself. /api/config needs Open WebUI.
    wait_for "$BASE_URL/api/config" 600
    python scripts/dev_seed.py
    python scripts/dev_check.py
}

cmd_down() {
    ensure_env
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
    ensure_env
    compose down -v
}

cmd_logs() {
    if [ $# -lt 1 ]; then
        echo "usage: $0 logs <service>" >&2
        exit 2
    fi
    compose logs -f --tail 200 "$1"
}

# A plain assignment, not "$(compose_files)" inside echo: set -e ignores a
# failing substitution in an argument, so the old one-liner printed an empty
# file list and exited 0 for an invalid LOCAL_MODEL.
cmd_model() {
    local files
    files="$(compose_files)"
    echo "LOCAL_MODEL=$(local_model); project: $PROJECT; compose files: $files"
}

case "${1:-}" in
    up) cmd_up ;;
    down) cmd_down ;;
    reset) cmd_reset ;;
    logs) shift; cmd_logs "$@" ;;
    model) cmd_model ;;
    config) shift; compose config "$@" ;;
    *)
        echo "usage: $0 up|down|reset|logs <service>|model|config" >&2
        exit 2
        ;;
esac
