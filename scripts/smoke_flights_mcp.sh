#!/usr/bin/env bash
# Smoke test for flights-mcp -- drives the stdio MCP server directly
# without an agent. Requires DUFFEL_API_KEY in env.

set -euo pipefail

if [[ -z "${DUFFEL_API_KEY:-}" ]]; then
  echo "DUFFEL_API_KEY not set; export it first." >&2
  exit 2
fi

cd "$(dirname "$0")/.." || exit 2

# Run the search_flights tool directly via call_search_flights --
# bypassing MCP stdio because we just want to verify Duffel is reachable.
python -c "
import asyncio, os, json
from flights_mcp.server import call_search_flights
async def go():
    result = await call_search_flights(
        api_key=os.environ['DUFFEL_API_KEY'],
        origin='LAX', destination='NRT', depart_date='2026-06-01',
        passengers=1,
    )
    print(json.dumps(result, indent=2)[:2000])
    if isinstance(result, dict) and 'error' in result:
        print('FAIL: got error:', result['error']); raise SystemExit(1)
    if not result:
        print('FAIL: empty offer list'); raise SystemExit(1)
    print(f'OK: got {len(result)} offers, first airline = {result[0][\"airline\"]}')
asyncio.run(go())
" 2>&1
