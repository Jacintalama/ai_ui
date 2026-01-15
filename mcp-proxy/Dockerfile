# mcp-proxy/Dockerfile
# Multi-Tenant MCP Proxy Gateway
#
# Supports two modes:
# - fastapi: Legacy OpenAPI mode (for External Tool Servers)
# - fastmcp: Native MCP Streamable HTTP (for Open WebUI native MCP)
# - dual: Both servers (default)
#
# Set MCP_MODE environment variable to choose mode.

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make start script executable
RUN chmod +x start.sh

# Expose ports:
# - 8000: FastAPI/OpenAPI (legacy) OR FastMCP (if single mode)
# - 8001: FastMCP (when running dual mode)
EXPOSE 8000 8001

# Environment variables
ENV MCP_MODE=dual
ENV DEBUG=true
ENV MCP_API_KEY=test-key

# Start the appropriate server(s)
CMD ["./start.sh"]
