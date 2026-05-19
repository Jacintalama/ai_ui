#!/usr/bin/env bash
# Layer-2 integration test for /aiui cronjob and /aiui aiuibuilder.
# Test keypair, not Discord's live public key. Safe to run locally + in CI.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/3] Running unit + integration tests..."
pytest webhook-handler/tests/ -v
pytest mcp-servers/tasks/tests/test_routes_projects_list.py -v
pytest mcp-servers/tasks/tests/test_auth_current_user.py -v

echo "[2/3] Running the signed-Discord-interaction integration test..."
pytest webhook-handler/tests/test_discord_e2e_local.py -v

echo "[3/3] All green. Layer 1 + Layer 2 pass."
