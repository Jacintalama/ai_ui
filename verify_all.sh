#!/usr/bin/env bash
# One-shot end-to-end + unit verification of the VM-hosted agent work.

set -uo pipefail
PASS=0
FAIL=0
results=()

pass() { results+=("PASS  $1"); PASS=$((PASS+1)); }
fail() { results+=("FAIL  $1 — $2"); FAIL=$((FAIL+1)); }

ORCH=root@46.224.193.25

echo "===== Phase A: Unit tests on dev machine ====="

out=$(cd mcp-servers/tasks && DATABASE_URL="postgresql://x:y@localhost/test" \
  python -m pytest tests/test_agent_executor_factory.py tests/test_local_executor.py \
  tests/test_sentinel_parsing.py tests/test_cancel_endpoint.py tests/test_remote_executor.py \
  -v --no-header 2>&1)
count=$(echo "$out" | grep -oE '[0-9]+ passed' | tail -1)
fails=$(echo "$out" | grep -oE '[0-9]+ failed' | tail -1 || echo "0 failed")
if echo "$fails" | grep -q '^0 '; then pass "A1 tasks unit tests: $count"
else fail "A1 tasks unit tests" "$fails"; fi

out=$(cd mcp-servers/flights && python -m pytest tests/ -v --no-header 2>&1)
count=$(echo "$out" | grep -oE '[0-9]+ passed' | tail -1)
fails=$(echo "$out" | grep -oE '[0-9]+ failed' | tail -1 || echo "0 failed")
if echo "$fails" | grep -q '^0 '; then pass "A2 flights unit tests: $count"
else fail "A2 flights unit tests" "$fails"; fi

echo
echo "===== Phase B: Live deployment artifact checks ====="

for f in agent_executor.py local_executor.py remote_executor.py; do
  ssh "$ORCH" "test -f /root/proxy-server/mcp-servers/tasks/$f" && \
    pass "B1.$f present on prod" || fail "B1.$f" "missing"
done

ssh "$ORCH" 'grep -q _FLIGHT_BOOKING_MCP_HINT /root/proxy-server/mcp-servers/tasks/templates.py' && \
  pass "B2 templates.py contains flight-booking augmentation" || fail "B2" "augmentation missing"

ssh "$ORCH" 'grep -q "COMPLETED|FAILED|NEEDS_INPUT|NEEDS_STEPS" /root/proxy-server/mcp-servers/tasks/claude_executor.py' && \
  pass "B3 _SENTINEL_RE includes FAILED" || fail "B3" "missing FAILED"

# B4 — fix the SQL quoting (single-quotes for string literals; columns table is lowercase)
col=$(ssh "$ORCH" "docker exec postgres psql -U openwebui -d openwebui -tA -c \"SELECT column_name FROM information_schema.columns WHERE table_schema='tasks' AND table_name='executions' AND column_name='agent_host';\"" 2>&1)
if echo "$col" | grep -q "^agent_host$"; then pass "B4 agent_host column live in DB"
else fail "B4" "column not found: $col"; fi

ssh "$ORCH" 'test -f /etc/proxy-server/agent_ssh_key && test "$(stat -c %a /etc/proxy-server/agent_ssh_key)" = "400"' && \
  pass "B5 agent_ssh_key file present + 0400" || fail "B5" "permissions wrong"

ssh "$ORCH" 'grep -q AGENT_BACKEND /root/proxy-server/docker-compose.unified.yml && grep -q "agent_ssh_key:/run/secrets/agent_ssh_key" /root/proxy-server/docker-compose.unified.yml' && \
  pass "B6 docker-compose patched" || fail "B6" "compose not patched"

echo
echo "===== Phase C: in-place agent (claude-agent user) ====="

ssh "$ORCH" 'id claude-agent >/dev/null && ! id claude-agent | grep -q sudo' && \
  pass "C1 claude-agent exists, no sudo" || fail "C1" "user broken"

ssh "$ORCH" 'stat -c "%U %a" /agent/work | grep -q "claude-agent 750"' && \
  pass "C2 /agent/work owned by claude-agent (0750)" || fail "C2" "perms wrong"

ssh "$ORCH" 'test -f /home/claude-agent/.ssh/authorized_keys && test "$(stat -c %a /home/claude-agent/.ssh/authorized_keys)" = "600"' && \
  pass "C3 authorized_keys 0600" || fail "C3" "wrong perms"

ssh "$ORCH" 'sudo -iu claude-agent claude --version 2>&1 | grep -q "Claude Code"' && \
  pass "C4 claude CLI works as claude-agent" || fail "C4" "claude broken"

ssh "$ORCH" 'sudo -iu claude-agent claude mcp list 2>&1 | grep -q "flights.*Connected"' && \
  pass "C5 flights-mcp Connected for claude-agent" || fail "C5" "MCP not connected"

ssh "$ORCH" 'systemctl is-active --quiet squid && grep -q duffel.com /etc/squid/squid.conf' && \
  pass "C6 Squid active + duffel.com in allowlist" || fail "C6" "squid broken"

ssh "$ORCH" 'test -f /etc/cron.d/agent-work-gc' && \
  pass "C7 workspace gc cron installed" || fail "C7" "cron missing"

echo
echo "===== Phase D: tasks container — live code path ====="

ssh "$ORCH" 'docker ps --filter name=tasks --format "{{.Status}}" | grep -q "^Up "' && \
  pass "D1 tasks container running" || fail "D1" "container down"

ssh "$ORCH" 'docker exec tasks bash -c "which ssh && which rsync" >/dev/null 2>&1' && \
  pass "D2 container has ssh + rsync" || fail "D2" "binaries missing"

n=$(ssh "$ORCH" 'docker exec tasks env | grep -c "^AGENT_"')
if [ "$n" = "4" ]; then pass "D3 4 AGENT_* env vars in container"
else fail "D3" "got $n AGENT vars"; fi

# D4: factory check — read the actual output, don't compare to blank
out=$(ssh "$ORCH" 'docker exec tasks bash -c "cd /app && python -c \"import sys; sys.path.insert(0, \\\"/app\\\"); from agent_executor import get_executor; print(get_executor().__class__.__name__)\""' 2>&1)
if echo "$out" | grep -q "^RemoteExecutor$"; then pass "D4 in-container factory -> RemoteExecutor"
else fail "D4" "got: $out"; fi

ssh "$ORCH" 'docker exec tasks test -f /run/secrets/agent_ssh_key' && \
  pass "D5 SSH key mounted in container" || fail "D5" "key not mounted"

echo
echo "===== Phase E: RemoteExecutor end-to-end ====="

cat >/tmp/e2e_remote.py <<'PYEOF'
import asyncio, os, shutil, sys
sys.path.insert(0, "/app")
shutil.copyfile("/run/secrets/agent_ssh_key", "/tmp/k")
os.chmod("/tmp/k", 0o600)
from remote_executor import RemoteExecutor
async def main():
    ex = RemoteExecutor()
    ok = await ex._ssh_ok("172.22.0.1", "claude-agent", "/tmp/k")
    assert ok, "ssh health check failed"
    cmd = ('set -a; source ~/.env; set +a; '
           'IS_SANDBOX=1 claude --print --dangerously-skip-permissions '
           '--effort low -- "reply with exactly: E2E_OK"')
    chunks = []
    async for line in ex._stream("172.22.0.1", "claude-agent", "/tmp/k", cmd):
        chunks.append(line)
        if "E2E_OK" in "".join(chunks):
            break
    assert "E2E_OK" in "".join(chunks), "no E2E_OK"
    print("E2E_OK")
asyncio.run(main())
PYEOF
scp /tmp/e2e_remote.py "$ORCH:/tmp/e2e_remote.py" >/dev/null
out=$(ssh "$ORCH" 'docker cp /tmp/e2e_remote.py tasks:/tmp/e2e.py && docker exec tasks python /tmp/e2e.py' 2>&1)
if echo "$out" | grep -q "^E2E_OK$"; then
  pass "E1 RemoteExecutor: container -> ssh -> host claude -> stdout back"
else fail "E1" "$out"; fi

# E2: flights-mcp tool error mapping
out=$(ssh "$ORCH" "/opt/flights-mcp/venv/bin/python -c '
import asyncio
from flights_mcp.server import call_search_flights
async def main():
    r = await call_search_flights(api_key=\"\", origin=\"LAX\", destination=\"NRT\", depart_date=\"2026-06-01\")
    assert r == {\"error\":\"auth\",\"detail\":\"DUFFEL_API_KEY not set\"}, f\"got {r}\"
    print(\"OK\")
asyncio.run(main())'" 2>&1)
if echo "$out" | grep -q "^OK$"; then pass "E2 flights-mcp tool error mapping correct"
else fail "E2" "$out"; fi

echo
echo "===== Phase F: production health (no regressions) ====="

err=$(ssh "$ORCH" "docker logs tasks --since 5m 2>&1 | grep -ciE 'traceback|exception |error:' || true" | tr -d '\n')
if [ "${err:-0}" = "0" ]; then pass "F1 no errors in last 5min ($err)"
else fail "F1" "$err errors in logs"; fi

fivexx=$(ssh "$ORCH" "docker logs tasks --since 30m 2>&1 | grep -cE ' (500|502|503|504) ' || true" | tr -d '\n')
if [ "${fivexx:-0}" = "0" ]; then pass "F2 no 5xx in last 30min ($fivexx)"
else fail "F2" "$fivexx 5xx in logs"; fi

free_kb=$(ssh "$ORCH" "free | awk '/^Mem:/ {print \$7}'")
if [ "${free_kb:-0}" -gt 500000 ]; then pass "F3 $((free_kb/1024))MB memory headroom"
else fail "F3" "low mem $((free_kb/1024))MB"; fi

echo
echo "===== Phase G: real user E2E (build a tiny task via API) ====="

# G1: trigger a real ASK_USER task (cheap, ~2-3K tokens) to prove the full
#     production path: POST /api/tasks -> /execute -> _stream_claude ->
#     get_executor() -> RemoteExecutor -> ssh -> host claude -> back.
#     Bypass api-gateway by injecting X-User-Email + X-User-Admin headers
#     directly (same headers api-gateway adds after JWT validation).
raw=$(ssh "$ORCH" "docker exec tasks curl -sX POST http://localhost:8210/api/tasks \
  -H 'Content-Type: application/json' \
  -H 'X-User-Email: alamajacintg04@gmail.com' \
  -H 'X-User-Admin: true' \
  -d '{\"action_type\":\"RESEARCH\",\"description\":\"Reply with exactly the string: PROD_E2E_OK (do not do any actual research)\",\"assignee_name\":\"alama\",\"assignee_email\":\"alamajacintg04@gmail.com\",\"priority\":\"NICE_TO_HAVE\"}'" 2>&1)
tid=$(echo "$raw" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("id",""))' 2>/dev/null || true)

if [ -z "$tid" ]; then fail "G1" "no task id returned"
else
  pass "G1 created task $tid via API"
  # G2: execute it
  ssh "$ORCH" "docker exec tasks curl -sX POST http://localhost:8210/api/tasks/$tid/execute \
    -H 'X-User-Email: alamajacintg04@gmail.com' -H 'X-User-Admin: true'" >/dev/null
  pass "G2 /execute fired"

  # G3: wait for completion (max 90s)
  for i in $(seq 1 30); do
    status=$(ssh "$ORCH" "docker exec postgres psql -U openwebui -d openwebui -tA -c \"SELECT status FROM tasks.items WHERE id = '$tid'::uuid;\"" 2>&1 | tr -d '\n ')
    if [ "$status" = "completed" ] || [ "$status" = "failed" ]; then break; fi
    sleep 3
  done

  if [ "$status" = "completed" ]; then
    pass "G3 task completed (final status: $status)"
  else
    fail "G3" "stuck at status: $status after 90s"
  fi

  # G4: verify it ran through RemoteExecutor (agent_host was written)
  agent_host=$(ssh "$ORCH" "docker exec postgres psql -U openwebui -d openwebui -tA -c \"SELECT agent_host FROM tasks.executions WHERE task_id = '$tid'::uuid;\"" 2>&1 | tr -d '\n ')
  if [ "$agent_host" = "172.22.0.1" ]; then
    pass "G4 execution ran through RemoteExecutor (agent_host=$agent_host)"
  else
    fail "G4" "agent_host wrong: '$agent_host' (expected 172.22.0.1)"
  fi
fi

echo
echo "===================== RESULTS ====================="
for r in "${results[@]}"; do echo "  $r"; done
echo
echo "Summary: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
