# mcp-servers/n8n/Dockerfile
# n8n MCP Server (czlonkowski/n8n-mcp) with mcpo OpenAPI wrapper
# Official pre-built image: Node 22, better-sqlite3, 1084 node docs
# Source: https://github.com/czlonkowski/n8n-mcp (13.7k stars)
FROM ghcr.io/czlonkowski/n8n-mcp:latest

USER root

# Install mcpo for OpenAPI compatibility with mcp-proxy
RUN apk add --no-cache python3 py3-pip && \
    pip3 install --break-system-packages mcpo

EXPOSE 8000

# Override entrypoint so mcpo can manage the subprocess
ENTRYPOINT []
CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"$MCP_API_KEY\" -- node /app/dist/mcp/index.js"]
