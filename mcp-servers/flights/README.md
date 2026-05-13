# flights-mcp

MCP server that exposes one tool, `search_flights`, returning real flight
offers from the Duffel sandbox API. Used by the IO App Builder's agent
to populate the `flight-booking` template with real data on demand.

Requires `DUFFEL_API_KEY` in the environment (sandbox tier is free).
