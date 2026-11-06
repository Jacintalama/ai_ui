# mcp-servers/github/Dockerfile
# GitHub MCP Server with mcpo HTTP wrapper
# Copy binary from official GitHub MCP Server image
FROM ghcr.io/github/github-mcp-server AS github-mcp

FROM python:3.11-slim

# Copy the GitHub MCP server binary from official image
COPY --from=github-mcp /server/github-mcp-server /usr/local/bin/github-mcp-server
COPY --from=github-mcp /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

# Install mcpo (MCP-to-OpenAPI wrapper)
RUN pip install --no-cache-dir mcpo "mcp<2"

WORKDIR /app

EXPOSE 8000

# Run mcpo with the GitHub MCP server binary
# GITHUB_PERSONAL_ACCESS_TOKEN is passed from Kubernetes environment
CMD ["sh", "-c", "mcpo --port 8000 --api-key \"$MCP_API_KEY\" -- /usr/local/bin/github-mcp-server stdio"]
