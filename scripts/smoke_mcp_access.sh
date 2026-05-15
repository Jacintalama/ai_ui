#!/usr/bin/env bash
# Smoke test the io-mcp-wrappers pipeline end-to-end.
#
# Prereqs:
#   - Task 10b deployed (Caddy + api-gateway updated)
#   - Task 11 provision script run (wrappers installed + claude mcp add'd on agent VM)
#   - Tasks 12-19 wrappers committed
#   - ORCH_HOST set (e.g. ai-ui.coolestdomain.win or 46.224.193.25)
#   - IO_USER_JWT set to a valid user JWT
#
# Usage:
#   ORCH_HOST=46.224.193.25 IO_USER_JWT=<jwt> ./scripts/smoke_mcp_access.sh
set -euo pipefail
: "${ORCH_HOST:?set ORCH_HOST to the orchestrator}"
: "${IO_USER_JWT:?set IO_USER_JWT to a valid user JWT}"

# Strategy: create a task, execute it, capture the streamed output, verify markers.
SLUG="smoke-mcp-$(date +%s)"
POSITIVE_PROMPT='Search the public web for "claude code release notes" using the io-web-search MCP. Then build a simple dashboard summarising the top 3 results using the io-dashboard MCP. End your message with COMPLETED.'

echo "==> [smoke 1/2] create task (slug=$SLUG)"
# Create a task with BUILD action type so it can be executed
task_response=$(curl -sS \
  -H "Authorization: Bearer $IO_USER_JWT" \
  -H "Content-Type: application/json" \
  -X POST "http://${ORCH_HOST}/api/tasks" \
  -d "$(jq -nc --arg desc "$POSITIVE_PROMPT" '{description:$desc,action_type:"BUILD",priority:"IMPORTANT",assignee:"self"}')")

echo "Task creation response:"
echo "$task_response" | head -20

# Extract task ID from response (assumes the response is JSON with an 'id' field)
TASK_ID=$(echo "$task_response" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -z "$TASK_ID" ]; then
  echo "FAIL: Could not extract task ID from response"
  exit 1
fi

echo "Created task ID: $TASK_ID"

echo "==> [smoke 2/4] execute task"
# NOTE: The endpoint is /api/tasks/{task_id}/execute
# The user_jwt is passed via Authorization header
exec_response=$(curl -sS \
  -H "Authorization: Bearer $IO_USER_JWT" \
  -H "Content-Type: application/json" \
  -X POST "http://${ORCH_HOST}/api/tasks/${TASK_ID}/execute")

echo "Execute response:"
echo "$exec_response" | head -20

echo "==> [smoke 3/4] stream execution log"
# Poll the execution log via the stream endpoint
# The stream endpoint returns SSE events: event, data, and done
echo "Streaming execution log..."

full_log=""
attempt=0
max_attempts=120  # 2 minutes with 1-second polls
while [ $attempt -lt $max_attempts ]; do
  stream=$(curl -sS "http://${ORCH_HOST}/api/tasks/${TASK_ID}/stream" \
    -H "Authorization: Bearer $IO_USER_JWT" \
    --max-time 5)

  # Parse SSE events
  if [ -n "$stream" ]; then
    # Extract data lines from SSE format
    log_chunk=$(echo "$stream" | grep -oP 'data: \K.*' || true)
    if [ -n "$log_chunk" ]; then
      full_log="${full_log}${log_chunk}"
    fi

    # Check for done event
    if echo "$stream" | grep -q 'event: done'; then
      echo "Stream completed"
      break
    fi
  fi

  attempt=$((attempt + 1))
  sleep 1
done

echo "----- execution log (first 100 lines) -----"
echo "$full_log" | head -100
echo "----- /log -----"

# Verification
echo "==> [smoke 4/4] verify markers in output"
ok=true

# Check for web-search MCP usage (accept multiple naming conventions)
if echo "$full_log" | grep -iE 'io-web-search|io_web_search|"name":\s*"web_search"|web search mcp' > /dev/null 2>&1; then
  echo "  found evidence of io-web-search MCP usage"
else
  echo "FAIL: no evidence of io-web-search being used"
  ok=false
fi

# Check for dashboard MCP usage
if echo "$full_log" | grep -iE 'io-dashboard|io_dashboard|"name":\s*"dashboard|dashboard.*mcp' > /dev/null 2>&1; then
  echo "  found evidence of io-dashboard MCP usage"
else
  echo "FAIL: no evidence of io-dashboard being used"
  ok=false
fi

# Check for COMPLETED sentinel
if echo "$full_log" | grep -q 'COMPLETED'; then
  echo "  found COMPLETED sentinel"
else
  echo "FAIL: no COMPLETED sentinel found"
  ok=false
fi

if $ok; then
  echo ""
  echo "Positive smoke test: PASS"
else
  echo ""
  echo "Positive smoke test: FAIL — see log above"
fi

# Negative: bad JWT
echo ""
echo "==> [smoke 2/2] negative test (intentionally bad JWT)"
NEG_TASK_RESPONSE=$(curl -sS \
  -H "Authorization: Bearer BAD-TOKEN-DO-NOT-LEAK-12345" \
  -H "Content-Type: application/json" \
  -X POST "http://${ORCH_HOST}/api/tasks" \
  -d "$(printf '{"description":"bad jwt test","action_type":"BUILD","priority":"IMPORTANT","assignee":"self"}')" || true)

echo "----- neg task response -----"
echo "$NEG_TASK_RESPONSE" | head -20
echo "----- /response -----"

# The orchestrator should reject the bad JWT at the auth layer (401)
# The token string itself MUST NEVER appear in the response.
if echo "$NEG_TASK_RESPONSE" | grep -q "BAD-TOKEN-DO-NOT-LEAK-12345"; then
  echo "FAIL: bad JWT token leaked into orchestrator response"
  exit 1
else
  echo "Negative test: PASS — bad token did not leak"
fi

if ! $ok; then
  echo ""
  echo "Overall result: FAIL (positive smoke broke)"
  exit 1
fi

echo ""
echo "Overall result: PASS — all smoke tests passed"
