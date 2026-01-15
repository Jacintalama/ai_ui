#!/bin/bash
# mcp-proxy/start.sh
# Start MCP Proxy in the appropriate mode

MODE="${MCP_MODE:-dual}"

echo "=== MCP Proxy Gateway ==="
echo "Mode: $MODE"

case "$MODE" in
    "fastmcp")
        # Native MCP Streamable HTTP only
        echo "Starting FastMCP server on port 8000..."
        python mcp_server.py
        ;;
    "fastapi")
        # Legacy FastAPI/OpenAPI only
        echo "Starting FastAPI server on port 8000..."
        uvicorn main:app --host 0.0.0.0 --port 8000
        ;;
    "dual")
        # Run both servers (FastMCP on 8001, FastAPI on 8000)
        echo "Starting dual mode..."
        echo "  FastAPI (OpenAPI): port 8000"
        echo "  FastMCP (Native MCP): port 8001"

        # Start FastMCP in background
        MCP_PORT=8001 python mcp_server.py &
        FASTMCP_PID=$!

        # Start FastAPI in foreground
        uvicorn main:app --host 0.0.0.0 --port 8000 &
        FASTAPI_PID=$!

        # Wait for both
        wait $FASTMCP_PID $FASTAPI_PID
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Valid modes: fastmcp, fastapi, dual"
        exit 1
        ;;
esac
